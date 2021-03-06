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

from __future__ import absolute_import, division, print_function

import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class ConvBNLayer(nn.Module):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        groups=1,
        act=None,
        name=None,
    ):
        super(ConvBNLayer, self).__init__()
        self.act = act
        self.conv = nn.Conv2d(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=(kernel_size - 1) // 2,
            groups=groups,
            bias=False,
        )

        self.bn = nn.BatchNorm2d(out_channels)

        if self.act == "relu":
            self.relu = nn.ReLU(inplace=True)

    def forward(self, inputs):
        y = self.conv(inputs)
        y = self.bn(y)
        if self.act == "relu":
            y = self.relu(y)
        return y


class LocalizationNetwork(nn.Module):
    def __init__(self, in_channels, num_fiducial, loc_lr, model_name):
        super(LocalizationNetwork, self).__init__()
        self.F = num_fiducial
        F = num_fiducial
        if model_name == "large":
            num_filters_list = [64, 128, 256, 512]
            fc_dim = 256
        else:
            num_filters_list = [16, 32, 64, 128]
            fc_dim = 64

        self.block_list = []
        for fno in range(0, len(num_filters_list)):
            num_filters = num_filters_list[fno]
            name = "loc_conv%d" % fno
            conv = ConvBNLayer(
                in_channels=in_channels,
                out_channels=num_filters,
                kernel_size=3,
                act="relu",
                name=name,
            )
            self.add_module(name, conv)
            self.block_list.append(conv)
            if fno == len(num_filters_list) - 1:
                pool = nn.AdaptiveAvgPool2d(1)
            else:
                pool = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
            in_channels = num_filters
            self.block_list.append(pool)
        name = "loc_fc1"
        1.0 / math.sqrt(num_filters_list[-1] * 1.0)
        self.fc1 = nn.Linear(in_channels, fc_dim)

        # Init fc2 in LocalizationNetwork
        # initial_bias = self.get_initial_fiducials()
        # initial_bias = initial_bias.view(-1)
        name = "loc_fc2"
        self.fc2 = nn.Linear(fc_dim, F * 2)
        self.out_channels = F * 2

    def forward(self, x):
        """
        Estimating parameters of geometric transformation
        Args:
            image: input
        Return:
            batch_C_prime: the matrix of the geometric transformation
        """
        x.shape[0]
        for block in self.block_list:
            x = block(x)
        x = x.squeeze(2).squeeze(2)
        x = self.fc1(x)

        x = F.relu(x)
        x = self.fc2(x)
        x = x.view(size=(-1, self.F, 2))
        return x

    def get_initial_fiducials(self):
        """ see RARE paper Fig. 6 (a) """
        F = self.F
        ctrl_pts_x = np.linspace(-1.0, 1.0, int(F / 2))
        ctrl_pts_y_top = np.linspace(0.0, -1.0, num=int(F / 2))
        ctrl_pts_y_bottom = np.linspace(1.0, 0.0, num=int(F / 2))
        ctrl_pts_top = np.stack([ctrl_pts_x, ctrl_pts_y_top], axis=1)
        ctrl_pts_bottom = np.stack([ctrl_pts_x, ctrl_pts_y_bottom], axis=1)
        initial_bias = np.concatenate([ctrl_pts_top, ctrl_pts_bottom], axis=0)
        return initial_bias


class GridGenerator(nn.Module):
    def __init__(self, in_channels, num_fiducial):
        super(GridGenerator, self).__init__()
        self.eps = 1e-6
        self.F = num_fiducial

        # initializer = nn.initializer.Constant(value=0.0)
        self.fc = nn.Linear(in_channels, 6)

    def forward(self, batch_C_prime, I_r_size):
        """
        Generate the grid for the grid_sampler.
        Args:
            batch_C_prime: the matrix of the geometric transformation
            I_r_size: the shape of the input image
        Return:
            batch_P_prime: the grid for the grid_sampler
        """
        C = self.build_C_torch()
        P = self.build_P_torch(I_r_size)

        inv_delta_C_tensor = (
            torch.tensor(self.build_inv_delta_C_torch(C))
            .float()
            .type_as(batch_C_prime)
        )
        P_hat_tensor = (
            torch.tensor(self.build_P_hat_torch(C, P))
            .float()
            .type_as(batch_C_prime)
        )

        inv_delta_C_tensor.detach()
        P_hat_tensor.detach()

        batch_C_ex_part_tensor = self.get_expand_tensor(batch_C_prime)

        batch_C_ex_part_tensor.detach()

        batch_C_prime_with_zeros = torch.cat(
            (batch_C_prime, batch_C_ex_part_tensor), dim=1
        )
        batch_T = torch.matmul(inv_delta_C_tensor, batch_C_prime_with_zeros)
        batch_P_prime = torch.matmul(P_hat_tensor, batch_T)
        return batch_P_prime

    def build_C_torch(self):
        """ Return coordinates of fiducial points in I_r; C """
        F = self.F
        ctrl_pts_x = np.linspace(-1.0, 1.0, int(F / 2))
        ctrl_pts_y_top = -1 * np.ones(int(F / 2))
        ctrl_pts_y_bottom = np.ones(int(F / 2))
        ctrl_pts_top = np.stack([ctrl_pts_x, ctrl_pts_y_top], axis=1)
        ctrl_pts_bottom = np.stack([ctrl_pts_x, ctrl_pts_y_bottom], axis=1)
        C = np.concatenate([ctrl_pts_top, ctrl_pts_bottom], axis=0)
        return torch.as_tensor(C)  # F x 2

    def build_P_torch(self, I_r_size):
        I_r_height, I_r_width = I_r_size
        I_r_grid_x = (
            np.arange(-I_r_width, I_r_width, 2) + 1.0
        ) / I_r_width  # self.I_r_width
        I_r_grid_y = (
            np.arange(-I_r_height, I_r_height, 2) + 1.0
        ) / I_r_height  # self.I_r_height
        P = np.stack(  # self.I_r_width x self.I_r_height x 2
            np.meshgrid(I_r_grid_x, I_r_grid_y), axis=2
        )
        return torch.as_tensor(
            P.reshape([-1, 2])
        )  # n (= self.I_r_width x self.I_r_height) x 2

    def build_inv_delta_C_torch(self, C):
        """ Return inv_delta_C which is needed to calculate T """
        F = self.F
        hat_C = np.zeros((F, F), dtype=float)  # F x F
        for i in range(0, F):
            for j in range(i, F):
                r = np.linalg.norm(C[i] - C[j])
                hat_C[i, j] = r
                hat_C[j, i] = r
        np.fill_diagonal(hat_C, 1)
        hat_C = (hat_C ** 2) * np.log(hat_C)
        # print(C.shape, hat_C.shape)
        delta_C = np.concatenate(  # F+3 x F+3
            [
                np.concatenate([np.ones((F, 1)), C, hat_C], axis=1),  # F x F+3
                np.concatenate(
                    [np.zeros((2, 3)), np.transpose(C)], axis=1
                ),  # 2 x F+3
                np.concatenate(
                    [np.zeros((1, 3)), np.ones((1, F))], axis=1
                ),  # 1 x F+3
            ],
            axis=0,
        )
        inv_delta_C = np.linalg.inv(delta_C)
        return torch.as_tensor(inv_delta_C)  # F+3 x F+3

    def build_P_hat_torch(self, C, P):
        F = self.F
        self.eps
        n = P.shape[0]  # n (= self.I_r_width x self.I_r_height)
        # P_tile: n x 2 -> n x 1 x 2 -> n x F x 2
        P_tile = np.tile(
            np.expand_dims(P, axis=1), (1, F, 1)
        )  # n x 2 -> n x 1 x 2 -> n x F x 2
        C_tile = np.expand_dims(C, axis=0)  # 1 x F x 2
        P_diff = P_tile - C_tile  # n x F x 2
        rbf_norm = np.linalg.norm(
            P_diff, ord=2, axis=2, keepdims=False
        )  # n x F
        rbf = np.multiply(
            np.square(rbf_norm), np.log(rbf_norm + self.eps)
        )  # n x F
        P_hat = np.concatenate([np.ones((n, 1)), P, rbf], axis=1)
        return torch.as_tensor(P_hat)  # n x F+3

    def get_expand_tensor(self, batch_C_prime):
        B, H, C = batch_C_prime.shape
        batch_C_prime = batch_C_prime.view((B, H * C))
        batch_C_ex_part_tensor = self.fc(batch_C_prime)
        batch_C_ex_part_tensor = batch_C_ex_part_tensor.view((-1, 3, 2))
        return batch_C_ex_part_tensor


class TPS(nn.Module):
    def __init__(self, in_channels, num_fiducial, loc_lr, model_name):
        super(TPS, self).__init__()
        self.loc_net = LocalizationNetwork(
            in_channels, num_fiducial, loc_lr, model_name
        )
        self.grid_generator = GridGenerator(
            self.loc_net.out_channels, num_fiducial
        )
        self.out_channels = in_channels

    def forward(self, image):
        image.detach()
        batch_C_prime = self.loc_net(image)
        batch_P_prime = self.grid_generator(batch_C_prime, image.shape[2:])
        batch_P_prime = batch_P_prime.view(
            -1, image.shape[2], image.shape[3], 2
        )
        batch_I_r = F.grid_sample(
            image, grid=batch_P_prime, align_corners=True
        )
        return batch_I_r
