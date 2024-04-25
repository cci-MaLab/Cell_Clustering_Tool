from torch import nn
import torch
import math
from torch.nn import Module
from local_attention import LocalAttention
from local_attention.transformer import LocalMHA, FeedForward, DynamicPositionBias, eval_decorator, exists, rearrange, top_k
import torch.nn.functional as F

class GRU_2(Module):
    def __init__(self, sequence_len=200, input_size=3, hidden_size=32, num_layers=1, classes=1):
        # call the parent constructor
        super(GRU_2, self).__init__()

        self.sequence_len = sequence_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        '''
        We cannot use the num_layers because Pytorch only provides the output for the last layer. The reason why we need
        to the intermediary layer is because of the mini-epoch approach that requires us to preserve those hidden states
        in each layer. We will have to manually create into a list the GRU layers.
        '''
        self.grus = nn.ModuleList([])
        for i in range(num_layers):
            if i == 0:
                self.grus.append(nn.GRU(input_size=input_size, hidden_size=self.hidden_size, bidirectional=True, batch_first=True))
            else:
                self.grus.append(nn.GRU(input_size=hidden_size*2, hidden_size=self.hidden_size, bidirectional=True, batch_first=True))

        self.fc = nn.Linear(hidden_size*2, classes)


        
    def forward(self, x, h0: list = []):
        if not h0:
            h0 = [None]*self.num_layers
        for i in range(self.num_layers):
            x, _ = self.grus[i](x, h0[i])

        x = self.fc(x)
        return x
    
    def forward_hidden(self, x):
        # This assumes that the data is unbatched
        h0s = []
        length = x.shape[0]
        for i in range(self.num_layers):           
            x, _ = self.grus[i](x)
            h0s.append(x.view(length, 2, self.hidden_size))

        return h0s

class GRU(Module):
    def __init__(self, sequence_len=200, input_size=3, hidden_size=32, num_layers=1, classes=1, use_attention=True, context_length=20):
        # call the parent constructor
        super(GRU, self).__init__()

        self.sequence_len = sequence_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.context_length = context_length
        self.use_attention = use_attention

        '''
        We cannot use the num_layers because Pytorch only provides the output for the last layer. The reason why we need
        to the intermediary layer is because of the mini-epoch approach that requires us to preserve those hidden states
        in each layer. We will have to manually create into a list the GRU layers.
        '''
        self.grus = nn.ModuleList([])
        for i in range(num_layers):
            if i == 0:
                self.grus.append(nn.GRU(input_size=input_size, hidden_size=self.hidden_size, bidirectional=True, batch_first=True))
            else:
                self.grus.append(nn.GRU(input_size=hidden_size*2, hidden_size=self.hidden_size, bidirectional=True, batch_first=True))

        if self.use_attention:
            self.local_attention = LocalAttention(dim=hidden_size*2,
                                            window_size=20, 
                                            causal=False, 
                                            look_forward=1, 
                                            look_backward=0,
                                            dropout=0.1,
                                            exact_windowsize=True,
                                            autopad=True)

        self.fc = nn.Linear(hidden_size*2, classes)
        # No activation function is used because we are using BCEWithLogitsLoss

        # We need to create the default positional embeddings
        #self.positional_embeddings = 

        
    def forward(self, x, h0: list = []):
        if not h0:
            h0 = [None]*self.num_layers
        for i in range(self.num_layers):
            x, _ = self.grus[i](x, h0[i])
        #x = self.positional_embeddings(x)
        if self.use_attention:
            x = self.local_attention(x, x, x)
        x = self.fc(x)
        return x
    
    def forward_hidden(self, x):
        # This assumes that the data is unbatched
        h0s = []
        length = x.shape[0]
        for i in range(self.num_layers):           
            x, _ = self.grus[i](x)
            h0s.append(x.view(length, 2, self.hidden_size))

        return h0s
    
    def gen_pe(max_length, d_model, n):
        # Taken from: https://medium.com/@hunter-j-phillips/positional-encoding-7a93db4109e6
        # calculate the div_term
        div_term = torch.exp(torch.arange(0, d_model, 2) * -(math.log(n) / d_model))
        # generate the positions into a column matrix
        k = torch.arange(0, max_length).unsqueeze(1)
        # generate an empty tensor
        pe = torch.zeros(max_length, d_model)
        # set the even values
        pe[:, 0::2] = torch.sin(k * div_term)
        # set the odd values
        pe[:, 1::2] = torch.cos(k * div_term)
        # add a dimension       
        pe = pe.unsqueeze(0)
        # the output has a shape of (1, max_length, d_model)
        return pe    


class LocalTransformer(nn.Module):
    """ 
    Taken from: https://github.com/lucidrains/local-attention
    Adjusted slightly to work with numerical non-tokenized data
    """
    def __init__(
        self,
        *,
        max_seq_len,
        dim=3,
        depth,
        causal = True,
        local_attn_window_size = 30,
        dim_head = 32,
        heads = 1,
        ff_mult = 2,
        attn_dropout = 0.,
        ff_dropout = 0.,
        use_xpos = False,
        xpos_scale_base = None,
        use_dynamic_pos_bias = False,
        slack = 50,
        **kwargs
    ):
        super().__init__()
        self.pos_emb = nn.Embedding(max_seq_len, dim)
        self.slack = slack

        self.max_seq_len = max_seq_len
        self.layers = nn.ModuleList([])

        self.local_attn_window_size = local_attn_window_size
        self.dynamic_pos_bias = None
        if use_dynamic_pos_bias:
            self.dynamic_pos_bias = DynamicPositionBias(dim = dim // 2, heads = heads)

        for _ in range(depth):
            self.layers.append(nn.ModuleList([
                LocalMHA(dim = dim, dim_head = dim_head, heads = heads, dropout = attn_dropout, causal = causal, window_size = local_attn_window_size, use_xpos = use_xpos, xpos_scale_base = xpos_scale_base, use_rotary_pos_emb = not use_dynamic_pos_bias, prenorm = True, **kwargs),
                FeedForward(dim = dim, mult = ff_mult, dropout = ff_dropout)
            ]))

        self.to_logits = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, 1, bias = False)
        )

    def forward(self, x, mask = None):
        n, device = x.shape[1], x.device

        assert n <= self.max_seq_len
        x = x + self.pos_emb(torch.arange(n, device = device))

        # dynamic pos bias
        attn_bias = None
        if exists(self.dynamic_pos_bias):
            w = self.local_attn_window_size
            attn_bias = self.dynamic_pos_bias(w, w * 2)

        # go through layers
        for attn, ff in self.layers:
            x = attn(x, mask = mask, attn_bias = attn_bias) + x
            x = ff(x) + x

        logits = self.to_logits(x)

        return torch.squeeze(logits[:, self.slack:-self.slack,:], dim=-1)