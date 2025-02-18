#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#
# Reference (https://ieeexplore.ieee.org/document/9625818)

"""Encoder modules."""

import torch
import inspect

from layers.conv_layer import NonCausalConv1d
from layers.conv_layer import CausalConv1d
from models.autoencoder.modules.residual_unit import NonCausalResidualUnit
from models.autoencoder.modules.residual_unit import CausalResidualUnit
from models.utils import check_mode


class EncoderBlock(torch.nn.Module):
    """ Encoder block (downsampling) """

    def __init__(
        self,
        in_channels,
        out_channels,
        stride,
        dilations=(1, 3, 9),
        bias=True,
        mode='causal',
    ):
        super().__init__()
        self.mode = mode
        if self.mode == 'noncausal':
            ResidualUnit = NonCausalResidualUnit
            Conv1d = NonCausalConv1d
        elif self.mode == 'causal':
            ResidualUnit = CausalResidualUnit
            Conv1d = CausalConv1d
        else:
            raise NotImplementedError(f"Mode ({self.mode}) is not supported!")

        self.res_units = torch.nn.ModuleList()
        for dilation in dilations:
            self.res_units += [
                ResidualUnit(in_channels, in_channels, dilation=dilation)]
        self.num_res = len(self.res_units)

        self.conv = Conv1d(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=(2 * stride),
            stride=stride,
            bias=bias,
        )
        
    def forward(self, x):
        for idx in range(self.num_res):
            x = self.res_units[idx](x)
        x = self.conv(x)
        return x
    
    def inference(self, x):
        check_mode(self.mode, inspect.stack()[0][3])
        for idx in range(self.num_res):
            x = self.res_units[idx].inference(x)
        x = self.conv.inference(x)
        return x


class Encoder(torch.nn.Module):
    def __init__(self,
        input_channels,
        encode_channels,
        channel_ratios=(2, 4, 8, 16),
        strides=(3, 4, 5, 5),
        kernel_size=7,
        bias=True,
        mode='causal',
    ):
        super().__init__()
        assert len(channel_ratios) == len(strides)
        self.mode = mode
        if self.mode == 'noncausal':
            Conv1d = NonCausalConv1d
        elif self.mode == 'causal':
            Conv1d = CausalConv1d
        else:
            raise NotImplementedError(f"Mode ({self.mode}) is not supported!")

        self.conv = Conv1d(
            in_channels=input_channels, 
            out_channels=encode_channels, 
            kernel_size=kernel_size, 
            stride=1, 
            bias=False)
        self.fusion_conv = torch.nn.ModuleList()
        self.conv_blocks = torch.nn.ModuleList()
        in_channels = encode_channels
        for idx, stride in enumerate(strides):
            out_channels = encode_channels * channel_ratios[idx]
            self.conv_blocks += [
                EncoderBlock(in_channels, out_channels, stride, bias=bias, mode=self.mode)]
            self.fusion_conv +=[
                Conv1d(in_channels=out_channels*2, out_channels=out_channels, kernel_size=1, stride=1, bias=False)
            ]
            in_channels = out_channels
        self.num_blocks = len(self.conv_blocks)
        self.out_channels = out_channels
    
    def forward(self, x): 
        x = self.conv(x)
        for i in range(self.num_blocks):
            x = self.conv_blocks[i](x)
        return x
    def fusion_forward(self, x, v, index=0): 
        x = self.conv(x)
        for i in range(self.num_blocks):
            x = self.conv_blocks[i](x)
            if i == index:
                x = torch.cat([x, v], dim=1)
                x = self.fusion_conv[i](x)
        return x
    def early_exit(self, x, index=0):
        x = self.conv(x)
        for i in range(self.num_blocks):
            x = self.conv_blocks[i](x)
            if i == index:
                break
        return x
    def encode(self, x):
        check_mode(self.mode, inspect.stack()[0][3])
        x = self.conv.inference(x)
        for i in range(self.num_blocks):
            x = self.conv_blocks[i].inference(x)
        return x


