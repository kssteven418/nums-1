# coding=utf-8
# Copyright (C) 2020 NumS Development Team.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import itertools

import tqdm
import numpy as np

from nums.core.array import utils as array_utils
import nums.core.array.selection as sel_module
from nums.core.array.view import ArrayView
from nums.core.array.application import ArrayApplication


def get_slices(size, index_multiplier=1, limit=None, basic_step=False):
    index_multiplier = [None] + list(range(-size * index_multiplier, size * index_multiplier + 1))
    items = list()
    for start, stop, step in itertools.product(index_multiplier, repeat=3):
        if step == 0 or (basic_step and step not in (None, 1)):
            continue
        items.append(slice(start, stop, step))
    if limit is None:
        return items
    else:
        return subsample(items, limit)


def subsample(items, max_items, seed=1337):
    rs = np.random.RandomState(seed)
    return np.array(items)[rs.choice(np.arange(len(items), dtype=int), max_items)].tolist()


def is_broadcastable(lshape, laccessor, rshape, raccessor):
    lsel = sel_module.BasicSelection.from_subscript(lshape, laccessor)
    rsel = sel_module.BasicSelection.from_subscript(rshape, raccessor)
    try:
        array_utils.broadcast_shape_to(rsel.get_output_shape(),
                                       lsel.get_output_shape())
        return True
    except ValueError as _:
        return False


def test_basic_select(app_inst: ArrayApplication):
    arr: np.ndarray = np.arange(5)
    block_shape = 3,
    slice_params = list(get_slices(size=10, index_multiplier=2, basic_step=True))
    pbar = tqdm.tqdm(total=len(slice_params))
    for slice_sel in slice_params:
        pbar.set_description(str(slice_sel))
        pbar.update(1)
        ba = app_inst.array(arr, block_shape=block_shape)
        bav = ArrayView.from_block_array(ba)
        res = (arr[slice_sel], bav[slice_sel].create().get())
        assert np.allclose(*res), str(res)


def test_basic_assign(app_inst: ArrayApplication):
    from_arr: np.ndarray = np.arange(5)
    block_shape = 3,
    slice_params = list(get_slices(size=10, index_multiplier=2, basic_step=True))
    pbar = tqdm.tqdm(total=len(slice_params))
    for slice_sel in slice_params:
        pbar.set_description(str(slice_sel))
        pbar.update(1)

        from_ba = app_inst.array(from_arr, block_shape=block_shape)
        from_bav = ArrayView.from_block_array(from_ba)

        to_arr: np.ndarray = np.zeros(5)
        to_ba = app_inst.array(to_arr, block_shape=block_shape)
        to_bav = ArrayView.from_block_array(to_ba)

        to_bav[slice_sel] = from_bav[slice_sel]
        to_arr[slice_sel] = from_arr[slice_sel]

        from_res = (from_arr, from_bav.create().get())
        assert np.allclose(*from_res), str(from_res)

        to_res = (to_arr, to_bav.create().get())
        assert np.allclose(*to_res), str(to_res)


def test_basic_assign_3axis(app_inst: ArrayApplication):

    def get_access_iterator(shape, block_shape, limit=None):
        num_axes = len(shape)
        accessor_start = list(map(lambda x: list(range(x)), shape))
        accessor_stop = list(map(lambda x: list(range(x + 1)), shape))
        accessor_step = list(map(lambda x: [1], shape))
        axis_accessors = []
        for i in range(num_axes):
            accessor_params = list(filter(lambda a: a[0] <= a[1],
                                          itertools.product(accessor_start[i],
                                                            accessor_stop[i],
                                                            accessor_step[i])))
            axis_accessors.append(accessor_params)
        accessor_iterator = list(itertools.product(*axis_accessors))
        if limit is not None:
            accessor_iterator = subsample(accessor_iterator, limit)
        return shape, block_shape, accessor_iterator

    access_modes = [
        lambda a1, a2, s: a1,
        lambda a1, a2, s: slice(None, None, None),
        lambda a1, a2, s: slice(a1, None, None),
        lambda a1, a2, s: slice(None, a1, None),
        lambda a1, a2, s: slice(a1, a2, None),
        # TODO: Enable below once arbitrary step-size is supported.
        # lambda a1, a2, s: slice(None, None, s),
        # lambda a1, a2, s: slice(a1, None, s),
        # lambda a1, a2, s: slice(None, a1, s),
        # lambda a1, a2, s: slice(a1, a2, s)
    ]

    num_axes = 3
    limit = 5

    lshape, lblock_shape, left_accessor_iterator = get_access_iterator(shape=(7, 5, 3),
                                                                       block_shape=(4, 3, 2),
                                                                       limit=limit)

    rshape, rblock_shape, right_accessor_iterator = get_access_iterator(shape=(5, 6, 4),
                                                                        block_shape=(2, 4, 3),
                                                                        limit=limit)

    mode_iterator = list(itertools.product(access_modes, repeat=num_axes))
    pbar = tqdm.tqdm(total=(len(left_accessor_iterator) *
                            len(right_accessor_iterator) *
                            len(mode_iterator)**2))

    def test_assignment(left_item, left_mode, right_item, right_mode):
        lshape, lblock_shape, laccessor = left_item
        laccessor = tuple(left_mode[i](*laccessor[i]) for i in range(num_axes))
        rshape, rblock_shape, raccessor = right_item
        raccessor = tuple(right_mode[i](*raccessor[i]) for i in range(num_axes))
        if not is_broadcastable(lshape, laccessor, rshape, raccessor):
            return False
        npA = np.zeros(np.product(lshape)).reshape(*lshape)
        npB = np.random.random_sample(np.product(rshape)).reshape(*rshape)
        baA = app_inst.array(npA, block_shape=lblock_shape)
        baB = app_inst.array(npB, block_shape=rblock_shape)
        bavA = ArrayView.from_block_array(baA)
        bavB = ArrayView.from_block_array(baB)
        assert np.allclose(npA[laccessor], bavA[laccessor].create().get())
        assert np.allclose(npB[raccessor], bavB[raccessor].create().get())
        npA[laccessor] = npB[raccessor]
        bavA[laccessor] = bavB[raccessor]
        assert np.allclose(npA, bavA.create().get())
        assert np.allclose(npB, bavB.create().get())
        return True

    num_valid = 0
    for laccessor in left_accessor_iterator:
        left_item = lshape, lblock_shape, laccessor
        for raccessor in right_accessor_iterator:
            right_item = rshape, rblock_shape, raccessor
            for left_mode in mode_iterator:
                for right_mode in mode_iterator:
                    if test_assignment(left_item, left_mode,
                                       right_item, right_mode):
                        num_valid += 1
                        pbar.set_description("num_valid=%d" % num_valid)
                    pbar.update(1)


if __name__ == "__main__":
    # pylint: disable=import-error
    from tests import conftest

    app_inst = conftest.get_app("serial")
    test_basic_select(app_inst)
    test_basic_assign(app_inst)
    test_basic_assign_3axis(app_inst)
