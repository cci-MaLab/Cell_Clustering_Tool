import numpy as np
import pandas as pd
import xarray as xr
from os.path import isdir, isfile
from os.path import join as pjoin
from os import listdir
from typing import Callable, List, Optional, Union
import dask.array as darr
import os

def open_minian(
    dpath: str, post_process: Optional[Callable] = None, return_dict=False
) -> Union[dict, xr.Dataset]:
    """
    Load an existing minian dataset.

    If `dpath` is a file, then it is assumed that the full dataset is saved as a
    single file, and this function will directly call
    :func:`xarray.open_dataset` on `dpath`. Otherwise if `dpath` is a directory,
    then it is assumed that the dataset is saved as a directory of `zarr`
    arrays, as produced by :func:`save_minian`. This function will then iterate
    through all the directories under input `dpath` and load them as
    `xr.DataArray` with `zarr` backend, so it is important that the user make
    sure every directory under `dpath` can be load this way. The loaded arrays
    will be combined as either a `xr.Dataset` or a `dict`. Optionally a
    user-supplied custom function can be used to post process the resulting
    `xr.Dataset`.

    Parameters
    ----------
    dpath : str
        The path to the minian dataset that should be loaded.
    post_process : Callable, optional
        User-supplied function to post process the dataset. Only used if
        `return_dict` is `False`. Two arguments will be passed to the function:
        the resulting dataset `ds` and the data path `dpath`. In other words the
        function should have signature `f(ds: xr.Dataset, dpath: str) ->
        xr.Dataset`. By default `None`.
    return_dict : bool, optional
        Whether to combine the DataArray as dictionary, where the `.name`
        attribute will be used as key. Otherwise the DataArray will be combined
        using `xr.merge(..., compat="no_conflicts")`, which will implicitly
        align the DataArray over all dimensions, so it is important to make sure
        the coordinates are compatible and will not result in creation of large
        NaN-padded results. Only used if `dpath` is a directory, otherwise a
        `xr.Dataset` is always returned. By default `False`.

    Returns
    -------
    ds : Union[dict, xr.Dataset]
        The resulting dataset. If `return_dict` is `True` it will be a `dict`,
        otherwise a `xr.Dataset`.

    See Also
    -------
    xarray.open_zarr : for how each directory will be loaded as `xr.DataArray`
    xarray.merge : for how the `xr.DataArray` will be merged as `xr.Dataset`
    """
    if isfile(dpath):
        ds = xr.open_dataset(dpath).chunk()
    elif isdir(dpath):
        dslist = []
        for d in listdir(dpath):
            arr_path = pjoin(dpath, d)
            if isdir(arr_path):
                arr = list(xr.open_zarr(arr_path).values())[0]
                arr.data = darr.from_zarr(
                    os.path.join(arr_path, arr.name), inline_array=True
                )
                dslist.append(arr)
        if return_dict:
            ds = {d.name: d for d in dslist}
        else:
            ds = xr.merge(dslist, compat="no_conflicts")
    if (not return_dict) and post_process:
        ds = post_process(ds, dpath)
    return ds

def main():
    data = open_minian("/N/project/Cortical_Calcium_Image/Miniscope data/05.2023_Tenth_group/AA058_D1/2023_05_05/11_02_42/Miniscope_2/sessions/S1/minian")
    # print(np.array(data["A"])[0,181:187,368:376])
    footprint = np.array(data["A"])
    xmax = 0
    ymax = 0
    for i in footprint:
        a,b = np.nonzero(i[:,:])
        x = np.unique(a)
        y = np.unique(b)
        xmax = max(len(x),xmax)
        ymax = max(len(y),ymax)
    print(xmax,ymax)  
    # for i in footprint:
    #     a,b = np.nonzero(footprint[0,:,:])
    #     x = np.unique(a)
    #     y = np.unique(b)
    #     if(len(x)<xmax):
    #         diff = xmax - len(x)
    #         if diff %2 ==1:
    #             add = int(diff/2)
    #             np.insert(x,)
    return


if __name__ == "__main__":
    main()