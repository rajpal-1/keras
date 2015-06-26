# -*- coding: utf-8 -*-
from __future__ import absolute_import

import theano
import theano.tensor as T
from theano.tensor.signal import downsample

from .. import activations, initializations
from ..utils.theano_utils import shared_zeros
from ..layers.core import Layer


class Convolution1D(Layer):
    def __init__(self, nb_filter, stack_size, filter_length,
        init='uniform', activation='linear', weights=None,
        image_shape=None, border_mode='valid', subsample_length=1,
        W_regularizer=None, b_regularizer=None, W_constraint=None, b_constraint=None):

        nb_row = 1
        nb_col = filter_length

        self.nb_filter = nb_filter
        self.stack_size = stack_size
        self.filter_length = filter_length
        self.subsample_length = subsample_length
        self.init = initializations.get(init)
        self.activation = activations.get(activation)
        self.subsample = (1, subsample_length)
        self.border_mode = border_mode
        self.image_shape = image_shape

        self.input = T.tensor4()
        self.W_shape = (nb_filter, stack_size, nb_row, nb_col)
        self.W = self.init(self.W_shape)
        self.b = shared_zeros((nb_filter,))

        self.params = [self.W, self.b]

        self.regularizers = [W_regularizer, b_regularizer]
        self.constraints = [W_constraint, b_constraint]

        if weights is not None:
            self.set_weights(weights)

    def get_output(self, train):
        X = self.get_input(train)

        conv_out = theano.tensor.nnet.conv.conv2d(X, self.W,
            border_mode=self.border_mode, subsample=self.subsample, image_shape=self.image_shape)
        output = self.activation(conv_out + self.b.dimshuffle('x', 0, 'x', 'x'))
        return output

    def get_config(self):
        return {"name":self.__class__.__name__,
            "nb_filter":self.nb_filter,
            "stack_size":self.stack_size,
            "filter_length":self.filter_length,
            "init":self.init.__name__,
            "activation":self.activation.__name__,
            "image_shape":self.image_shape,
            "border_mode":self.border_mode,
            "subsample_length":self.subsample_length}


class MaxPooling1D(Layer):
    def __init__(self, pool_length=2, stride=None, ignore_border=True):
        super(MaxPooling1D,self).__init__()
        self.pool_length = pool_length

        if stride is not None:
            self.stride = (1, stride)

        self.input = T.tensor4()
        self.poolsize = (1, pool_length)
        self.ignore_border = ignore_border

    def get_output(self, train):
        X = self.get_input(train)
        output = downsample.max_pool_2d(X, ds=self.poolsize, st=self.stride, ignore_border=self.ignore_border)
        return output

    def get_config(self):
        return {"name":self.__class__.__name__,
                "pool_length":self.pool_length,
                "ignore_border":self.ignore_border,
                "subsample_length": self.subsample_length}



class Convolution2D(Layer):
    def __init__(self, nb_filter, stack_size, nb_row, nb_col,
        init='glorot_uniform', activation='linear', weights=None,
        image_shape=None, border_mode='valid', subsample=(1,1),
        W_regularizer=None, b_regularizer=None, W_constraint=None, b_constraint=None):
        super(Convolution2D,self).__init__()

        self.init = initializations.get(init)
        self.activation = activations.get(activation)
        self.subsample = subsample
        self.border_mode = border_mode
        self.image_shape = image_shape
        self.nb_filter = nb_filter
        self.stack_size = stack_size
        self.nb_row = nb_row
        self.nb_col = nb_col

        self.input = T.tensor4()
        self.W_shape = (nb_filter, stack_size, nb_row, nb_col)
        self.W = self.init(self.W_shape)
        self.b = shared_zeros((nb_filter,))

        self.params = [self.W, self.b]

        self.regularizers = [W_regularizer, b_regularizer]
        self.constraints = [W_constraint, b_constraint]

        if weights is not None:
            self.set_weights(weights)

    def get_output(self, train):
        X = self.get_input(train)

        conv_out = theano.tensor.nnet.conv.conv2d(X, self.W,
            border_mode=self.border_mode, subsample=self.subsample, image_shape=self.image_shape)
        output = self.activation(conv_out + self.b.dimshuffle('x', 0, 'x', 'x'))
        return output

    def get_config(self):
        return {"name":self.__class__.__name__,
                "nb_filter":self.nb_filter,
                "stack_size":self.stack_size,
                "nb_row":self.nb_row,
                "nb_col":self.nb_col,
                "init":self.init.__name__,
                "activation":self.activation.__name__,
                "image_shape":self.image_shape,
                "border_mode":self.border_mode,
                "subsample":self.subsample}


class MaxPooling2D(Layer):
    def __init__(self, poolsize=(2, 2), stride=None, ignore_border=True):
        super(MaxPooling2D,self).__init__()

        self.poolsize = poolsize
        self.stride = stride
        self.ignore_border = ignore_border

        self.input = T.tensor4()

    def get_output(self, train):
        X = self.get_input(train)
        output = downsample.max_pool_2d(X, ds=self.poolsize, st=self.stride, ignore_border=self.ignore_border)
        return output

    def get_config(self):
        return {"name":self.__class__.__name__,
                "poolsize":self.poolsize,
                "ignore_border":self.ignore_border,
                "stride": self.stride}



# class ZeroPadding2D(Layer): TODO

# class Convolution3D: TODO

# class MaxPooling3D: TODO

