from ml_training.dataset import (GRUDataset, TestDataset, ValDataset)
from ml_training.model import GRU
from ml_training import config
from torch.nn import BCEWithLogitsLoss
from torch.optim import Adam
from torch.utils.data import DataLoader
from tqdm import tqdm
import matplotlib.pyplot as plt
import torch
import time
import numpy as np
from sklearn.metrics import f1_score, roc_auc_score, roc_curve, precision_score, recall_score, confusion_matrix, accuracy_score, ConfusionMatrixDisplay
from sklearn.model_selection import train_test_split

def train(): 
	# load the image and mask filepaths in a sorted manner
	path = config.DATASET_PATH

	# create the train and test datasets
	trainDS = GRUDataset(normalPaths=path, test_split=config.TEST_SIZE,
					     val_split=config.VAL_SIZE, section_len=config.SECTION_LEN)
	valDS = ValDataset(data = trainDS.get_data(), indices=trainDS.val_indices, unit_ids=trainDS.unit_ids)
	testDS = TestDataset(data=trainDS.get_data(), unit_ids=trainDS.test_unit_ids)
	# create the training and test data loaders
	trainLoader = DataLoader(trainDS, shuffle=True,
		batch_size=config.BATCH_SIZE, pin_memory=config.PIN_MEMORY,
		num_workers=24)
	testLoader = DataLoader(testDS, shuffle=False,
		batch_size=config.BATCH_SIZE, pin_memory=config.PIN_MEMORY,
		num_workers=24)
	valLoader = DataLoader(valDS, shuffle=False,
		batch_size=config.BATCH_SIZE, pin_memory=config.PIN_MEMORY,
		num_workers=24)

	# initialize our CNN model
	gru = GRU().to(config.DEVICE)
	# initialize loss function and optimizer

	lossFunc = BCEWithLogitsLoss()
	opt = Adam(gru.parameters(), lr=config.INIT_LR)
	# calculate steps per epoch for training and validation set
	trainSteps = len(trainDS) // config.BATCH_SIZE * len(trainDS.unit_ids)
	valSteps = np.max([len(valDS) // config.BATCH_SIZE * len(trainDS.unit_ids), 1])
	# initialize a dictionary to store training history
	H = {"train_loss": [], "val_loss": []}

	# loop over epochs
	print("[INFO] training the network...")
	startTime = time.time()
	"""
	Due to the way we have set up our dataset, we have both a small and large epoch. The small epoch is per cell and the large epoch is per dataset.
	This is necessary as we need to save the hidden states on each intermediate pass
	"""
	for e in tqdm(range(config.NUM_EPOCHS)):
		# initialize the total training and validation loss
		totalTrainLoss = 0
		totalValLoss = 0
		for u in range(trainDS.unit_ids):
			trainDS.small_epoch = u
			# We need to get the local hidden states for the current unit
			with torch.no_grad():
				gru.eval()
				sample = trainDS.get_current_sample()
				trainDS.hidden_states = gru.forward_hidden(sample)

			# set the model in training mode
			gru.train()
			# loop over the training set
			for (i, (x, y)) in enumerate(tqdm(trainLoader), leave=False):
				# send the input to the device
				(x, y) = (x.to(config.DEVICE), y.to(config.DEVICE))
				# perform a forward pass and calculate the training loss
				pred = gru(x)
				loss = lossFunc(pred, y)
				# first, zero out any previously accumulated gradients, then
				# perform backpropagation, and then update model parameters
				opt.zero_grad()
				loss.backward()
				opt.step()
				# add the loss to the total training loss so far
				totalTrainLoss += loss
			trainLoader.dataset.random_subsample()
		
		# switch off autograd
		with torch.no_grad():
			# set the model in evaluation mode
			gru.eval()
			for u in tqdm(range(trainDS.unit_ids), leave=False):
				valDS.small_epoch = u
				sample = valDS.get_current_sample()
				trainDS.hidden_states = gru.forward_hidden(sample)
				# loop over the validation set
				for (x, y) in valLoader:
					# send the input to the device
					(x, y) = (x.to(config.DEVICE), y.to(config.DEVICE))
					# make the predictions and calculate the validation loss
					pred = gru(x)
					y = y.unsqueeze(1)
					totalValLoss += lossFunc(pred, y)
		# calculate the average training and validation loss
		avgTrainLoss = totalTrainLoss / trainSteps
		avgValLoss = totalValLoss / valSteps
		# update our training history
		H["train_loss"].append(avgTrainLoss.cpu().detach().numpy())
		H["val_loss"].append(avgValLoss.cpu().detach().numpy())
		# print the model training and validation information
		print("[INFO] EPOCH: {}/{}".format(e + 1, config.NUM_EPOCHS))
		print("Train loss: {:.6f}, Val loss: {:.4f}".format(
			avgTrainLoss, avgValLoss))
		
	
	# display the total time needed to perform the training
	endTime = time.time()
	print("[INFO] total time taken to train the model: {:.2f}s".format(
		endTime - startTime))

	# plot the training loss
	plt.style.use("ggplot")
	plt.figure()
	plt.plot(H["train_loss"], label="train_loss")
	plt.plot(H["val_loss"], label="val_loss")
	plt.title("Training Loss on Dataset")
	plt.xlabel("Epoch #")
	plt.ylabel("Loss")
	plt.legend(loc="lower left")
	plt.savefig(config.PLOT_PATH)
	# serialize the model to disk
	torch.save(gru, config.MODEL_PATH)

	# Start testing
	gru.eval()
	# initialize lists to store predictions and ground-truth
	preds = []
	gt = []
	# switch off autograd
	with torch.no_grad():
		# loop over the test set
		for (x, y) in tqdm(testLoader):
			# send the input to the device
			x = x.to(config.DEVICE)
			# make the predictions and add them to the list
			pred = gru(x)
			pred = torch.sigmoid(pred)
			pred = pred.cpu().detach().numpy()
			preds.extend(pred)
			# add the ground-truth to the list
			gt.extend(y.numpy())
	
	preds = np.array(preds)
	gt = np.array(gt)
	# calculate the accuracy
	acc = accuracy_score(gt, preds.round())
	print("[INFO] Accuracy: {:.4f}".format(acc))
	# calculate Precision and Recall per class
	precision = precision_score(gt, preds.round())
	recall = recall_score(gt, preds.round())
	print("[INFO] Transient Event Precision: {:.4f}".format(precision))
	print("[INFO] Transient Event Recall: {:.4f}".format(recall))
	# precision and recall for other class
	precision = precision_score(gt, preds.round(), pos_label=0)
	recall = recall_score(gt, preds.round(), pos_label=0)
	print("[INFO] No Transient Event Precision: {:.4f}".format(precision))
	print("[INFO] No Transient Event Recall: {:.4f}".format(recall))
	# Get confusion Matrix plot
	cm = confusion_matrix(gt, preds.round())
	disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["No Transient Event", "Transient Event"])
	# Save confusion matrix plot
	disp.plot()
	plt.savefig("confusion_matrix.png")	
	# calculate the F1 score and AUC ROC score	
	f1 = f1_score(gt, preds.round())
	print("[INFO] F1 score: {:.4f}".format(f1))
	# calculate the AUC ROC score
	auc = roc_auc_score(gt, preds)
	print("[INFO] AUC ROC score: {:.4f}".format(auc))
	# Visualize ROC
	fpr, tpr, _ = roc_curve(gt, preds)
	plt.style.use("ggplot")
	plt.figure()
	plt.plot(fpr, tpr, label="ROC curve")
	plt.title("ROC Curve")
	plt.xlabel("False Positive Rate")
	plt.ylabel("True Positive Rate")
	plt.legend(loc="lower right")
	plt.savefig("roc.png")