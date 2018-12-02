from __future__ import division

import torch
import torch.nn as nn
import torch.nn.functional as F 
from torch.autograd import Variable
import numpy as np 

def parse_cfg(cfgfile):
	"""

	Takes a configuration file

	Returns a list of blocks. Each block describes a block in the 
	network to be built. Block is represented as a dict in the list

	"""

	# Save the contents of the cfg file in a list of strings

	"""
	New ideas learned:
	- you can build arrays using this sort of functional approach
	- you can left and right strip strings
	"""
	file = open(cfgfile, 'r')
	lines = file.read().split('\n')
	lines = [x for x in lines if len(x) > 0]
	lines = [x for x in lines if x[0] != '#']
	lines = [x.rstrip().lstrip() for x in lines]

	# Then we loop over the resultant list to get blocks
	"""
	New ideas learned
	- use [1:-1] to get the internal portion of a string
	- you can use line.split by some character to split it
	"""
	block = {}
	blocks = []

	for line in lines:
		if line[0] == "[":
			if len(block) != 0:
				blocks.append(block)
				block = {}
			block["type"] = line[1:-1].rstrip()
		else:
			key, value = line.split("=")
			block[key.rstrip()] = value.lstrip()
	blocks.append(block)

	return blocks

	# We need to create our own modules for the rest of the layers
	# by extending the nn.Module class

	def create_modules(blocks):
		net_info = blocks[0]
		# nn.ModuleList is a class almost like a normal list containing
		# nn.Module objects. 
		module_list = nn.ModuleList()
		# Need to keep track of number of filters in the layer on which 
		# the convolutional layer is being applied. Here, 3 RGB channels
		# therefore prev_filters = 3
		prev_filters = 3
		output_filters = []

		# Want to iterate over the list of blocks and create a module for
		# each block as we go
		for index, x in enumerate(blocks[1:]):
			module = nn.Sequential()

			# check the type of block
			# create a new module for the block
			# append to module_list

			if (x["type"] == "convolutional"):
				# Get the info about the layer
				activation = x["activation"]
				try:
					batch_normalize = int(x["batch_normalize"])
					bias = False
				except:
					batch_normalize = 0
					bias = True

				filters = int(x["filters"])
				padding = int(x["pad"])
				kernel_size = int(x["size"])
				stride = int(x["stride"])

				if padding:
					pad = (kernel_size - 1) // 2
				else:
					pad = 0

				# Add the convolutional layer
				conv = nn.Conv2D(prev_filters, filters, kernel_size, stride, pad, bias=bias)
				module.add_module("conv_{0}".format(index), conv)

				# Add the batch norm layer
				if batch_normalize:
					bn = nn.BatchNorm2d(filters)
					module.add_module("batch_norm_{0}".format(index), bn)

				# Check the activation
				# It is either linear or a leaky ReLu for YOLO
				if activation == "leaky":
					activn = nn.LeakyReLU(0.1, inplace=True)
					module.add_module("leaky_{0}".format(index), bn)

			# If it's an upsampling layer
			# We use bilinear2dUpsampling
			elif (x["type"] == "upsample"):
				stride = int(x["stride"])
				upsample = nn.Upsample(scale_factor = 2, mode = "bilinear")
				module.add_module("upsample_{}".format(index), upsample)

			# If it's a route layer
			elif (x["type"] == "route"):
				x["layers"] = x["layers"].split(',')
				# Start of a route
				start = int(x["layers"][0])
				# end, if there exists one
				try:
					end = int(x["layers"][1])
				except:
					end = 0
				# Positive annotation
				if start > 0:
					start = start - index
				if end > 0:
					end = end - index

				route = EmptyLayer()
				module.add_module("route_{0}".format(index), route)
				if end < 0:
					filters = output_filters[index + start] + output_filters[index + end]
				else:
					filters = output_filters[index + start]

				shortcut corresponds to skip connection

