# copyright (c) 2020 PaddlePaddle Authors. All Rights Reserve.
#
# Modifications copyright (c) 2021 DocYard Authors. All Rights Reserve.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import random

import numpy as np
from torch.utils.data import Dataset

from ucr.core.preprocess import preprocess

log = logging.getLogger(__name__)


class SimpleDataSet(Dataset):
    def __init__(self, config, preprocess, logger, seed=None):
        super(SimpleDataSet, self).__init__()
        self.logger = logger

        self.delimiter = config.get("delimiter", "\t")
        label_file_list = config.pop("label_file_list")
        data_source_num = len(label_file_list)
        ratio_list = config.get("ratio_list", [1.0])
        if isinstance(ratio_list, (float, int)):
            ratio_list = [float(ratio_list)] * int(data_source_num)

        assert (
            len(ratio_list) == data_source_num
        ), "The length of ratio_list should be the same as the file_list."
        self.data_dir = config["data_dir"]
        self.do_shuffle = config["shuffle"]

        self.seed = seed
        log.info("Initialize indexs of datasets:%s" % label_file_list)
        self.data_lines = self.get_image_info_list(label_file_list, ratio_list)
        self.data_idx_order_list = list(range(len(self.data_lines)))
        self.ops = preprocess

    def get_image_info_list(self, file_list, ratio_list):
        if isinstance(file_list, str):
            file_list = [file_list]
        data_lines = []
        for idx, file in enumerate(file_list):
            with open(file, "rb") as f:
                lines = f.readlines()
                random.seed(self.seed)
                lines = random.sample(
                    lines, round(len(lines) * ratio_list[idx])
                )
                data_lines.extend(lines)
        return data_lines

    def __getitem__(self, idx):
        file_idx = self.data_idx_order_list[idx]
        data_line = self.data_lines[file_idx]
        try:
            data_line = data_line.decode("utf-8")
            substr = data_line.strip("\n").split(self.delimiter)
            file_name = substr[0]
            label = substr[1]
            img_path = os.path.join(self.data_dir, file_name)
            data = {"img_path": img_path, "label": label}
            if not os.path.exists(img_path):
                raise Exception("{} does not exist!".format(img_path))
            with open(data["img_path"], "rb") as f:
                img = f.read()
                data["image"] = img
            outs = preprocess(data, self.ops)

        except Exception as e:
            self.log.error(
                "When parsing line {}, error happened with msg: {}".format(
                    data_line, e
                )
            )
            outs = None
        if outs is None:
            return self.__getitem__(np.random.randint(self.__len__()))
        return outs

    def __len__(self):
        return len(self.data_idx_order_list)
