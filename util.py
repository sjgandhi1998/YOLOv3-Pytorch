from __future__ import division

import torch
import torch.nn as nn
import torch.nn.functional as F 
from torch.autograd import Variable
import numpy as np 
import cv2

"""

predict_transform takes in 5 params
- prediction (out output)
- inp_dim is the input dimensions
- anchors
- num_classes
- optional CUDA flag

"""

def predict_transform(prediction, inp_dim, anchors, num_classes, CUDA = True):
	"""

	This function takes a detection feature map and turns it into a 
	2-D tensor, where each row of the tensor corresponds to attributes
	of a bounding box

	"""

	batch_size = prediction.size(0)
	stride = inp_dim // prediction.size(2)
	grid_size = inp_dim // stride
	bbox_attrs = 5 + num_classes
	num_anchors = len(anchors)

	prediction = prediction.view(batch_size, bbox_attrs*num_anchors, grid_size*grid_size)
	prediction = prediction.transpose(1,2).contiguous()
	prediction = prediction.view(batch_size, grid_size*grid_size*num_anchors, bbox_attrs)

	anchors = [(a[0]/stride, a[1]/stride) for a in anchors]

	# Sigmoid the center_X, center_Y, and object confidence
	prediction[:,:,0] = torch.sigmoid(prediction[:,:,0])
	prediction[:,:,1] = torch.sigmoid(prediction[:,:,1])
	prediction[:,:,4] = torch.sigmoid(prediction[:,:,4])

	# Add the center offsets
	grid = np.arange(grid_size)
	a,b = np.meshgrid(grid, grid)

	x_offset = torch.FloatTensor(a).view(-1,1)
	y_offset = torch.FloatTensor(b).view(-1,1)

	if CUDA:
		x_offset = x_offset.cuda()
		y_offset = y_offset.cuda()

	x_y_offset = torch.cat((x_offset, y_offset), 1).repeat(1, num_anchors).view(-1,2).unsqueeze(0)

	prediction[:,:,:2] += x_y_offset

	# Apply the anchors to the dimensions of the bounding box

	# log space transform height and the width
	anchors = torch.FloatTensor(anchors)

	if CUDA:
		anchors = anchors.cuda()

	anchors = anchors.repeat(grid_size*grid_size, 1).unsqueeze(0)
	prediction[:,:,2:4] = torch.exp(prediction[:,:,2:4])*anchors

	# Apply sigmoid activation to the class scores
	prediction[:,:,5:(5+num_classes)] = torch.sigmoid((prediction[:,:,5:(5+num_classes)]))

	# Last, want to resize the detections map to size of input image
	prediction[:,:,:4] *= stride

	return prediction

# There are multiple true detections of the same class so we use
# a function called unique to get classes present in any given image

def unique(tensor):
	tensor_np = tensor.cpu().numpy()
	unique_np = np.unique(tensor_np)
	unique_tensor = torch.from_numpy(unique_np)

	tensor_rest = tensor.new(unique_tensor.shape)
	tensor_rest.copy_(unique_tensor)
	return tensor_res

# This is the function bbox_iou to return the iou of two bounding boxes

def bbox_iou(box1, box2):
	# Get the coordinates of bounding boxes
    b1_x1, b1_y1, b1_x2, b1_y2 = box1[:,0], box1[:,1], box1[:,2], box1[:,3]
    b2_x1, b2_y1, b2_x2, b2_y2 = box2[:,0], box2[:,1], box2[:,2], box2[:,3]

    # get the coordinates of the intersection rectangle
    inter_rect_x1 = torch.max(b1_x1, b2_x1)
    inter_rect_y1 = torch.max(b1_y1, b2_y1)
    inter_rect_x2 = torch.min(b1_x2, b2_x2)
    inter_rect_y2 = torch.min(b1_y2, b2_y2)

    # Intersection area
    inter_area = torch.clamp(inter_rect_x2 - inter_rect_x1 + 1, min = 0) * torch.clamp(inter_rect_y2 - inter_rect_y1 + 1, min = 0)


# We need a function that outputs objectness scores and
# non-maximal suppression

def write_results(prediction, confidence, num_classes, nms_conf = 0.4):
	# For every bounding box having an objectness score below a threshold.
	# we set the value of its every attributes to zero
	conf_mask = (prediction[:,:,4] > confidence).float().unsqueeze(2)
	prediction = prediction*conf_mask

	"""
	What is intersection over union?

	Ans: evaluation metric used to measure the accuracy of an object detector
	on a particular dataset. IoU = (Area of overlap)/(Area of Union)
	"""

	box_corner = prediction.new(prediction.shape)
	box_corner[:,:,0] = (prediction[:,:,0] - prediction[:,:,2]/2)
	box_corner[:,:,1] = (prediction[:,:,1] - prediction[:,:,3]/2)
	box_corner[:,:,2] = (prediction[:,:,0] + prediction[:,:,2]/2)
	box_corner[:,:,3] = (prediction[:,:,1] + prediction[:,:,3]/2)
	prediction[:,:,:4] = box_corner[:,:,:4]

	batch_size = prediction.size(0)
	write = False

	for ind in range(batch_size):
		image_pred = prediction[ind]

		# Each bounding box row has 85 attributes, out of which are
		# 80 class scores. We only want the class score with the max
		# value. 

		max_conf, max_conf_score = torch.max(image_pred[:, 5:5+num_classes], 1)
		max_conf = max_conf.float().unsqueeze(1)
		max_conf_score = max_conf_score.float().unsqueeze(1)
		seq = (image_pred[:,:5], max_conf, max_conf_score)
		image_pred = torch.cat(seq, 1)

		# Get rid of the bounding box rows have object confidence less than 0
		non_zero_ind = (torch.nonzero(image_pred[:,4]))
		try:
			image_pred_ = image_pred[non_zero_ind.squeeze(), :].view(-1, 7)
		except:
			continue

		# For PyTorch 0.4 compatibility
		# Since the above code with not raise exception for no detection
		# as scalars are supported in PyTorch 0.4
		if image_pred_.shape[0] == 0:
			continue

		# let's get the classes detected in an image
		img_classes = unique(image_pred_[:,-1])

		for cls in img_classes:
			# perform NMS

			cls_mask = image_pred_*(image_pred_[:,-1] == cls).float().unsqueeze(1)
			class_mask_ind = torch.nonzero(cls_mask[:, -2]).squeeze()
			image_pred_class = image_pred_[class_mask_ind].view(-1,7)

			# sort the detections such that the entry with the maximum objectness
			# confidence is at the top
			conf_sort_index = torch.sort(image_pred_class[:,4], descending = True)[1]
			image_pred_class = image_pred_class[conf_sort_index]
			idx = image_pred_class.size(0)

			for i in range(idx):
				# Get the IOUs of all boxes that come after the one we are looking at
				# in the loop
				try:
					# gives the IOU (intersection over union) of the box indexed by i
					# with all of the bounding boxes having indices higher than i
					ious = bbox_iou(image_pred_class[i].unsqueeze(0),image_pred_class[i+1:])
				except ValueError:
					break

				except IndexError:
					break

				# Zero out all the detections that have IoU > threshhold
				iou_mask = (ious < nms_conf).float().unsqueeze(1)
				image_pred_class[i+1:] *= iou_mask

				# Remove the non-zero entries
				non_zero_ind = torch.nonzero(image_pred_class[:,4]).squeeze()
				image_pred_class = image_pred_class[non_zero_ind].view(-1,7)

			# The function write_results is supposed to output a tensor of shape
			# Dx8 where D is the true detections in all of the images, represented by a row
			# We don't initialize the output tensor unless we have a detection to assign it.
			# Once it has been initialized, we concatenate subsequent detections to it.
			batch_ind = image_pred_class.new(image_pred_class(0), 1).fill_(ind)
			# Repeat the batch_id for as many detections of the class cls in the image
			seq = batch_ind, image_pred_class

			if not write:
				output = torch.cat(seq, 1)
				write = True 
			else:
				out = torch.cat(seq, 1)
				output = torch.cat((output, out))

			# At the end of the function we check whether output has been initialized
			# at all or not

	try:
		return output
	except:
		return 0

# load_classes is a function that returns a dict which maps the index of every class
# to a string of its name

def load_classes(namesfile):
	fp = open(namesfile, "r")
	names = fp.read().split("\n")[:-1]
	return names 

# Write a function to resize image, keeping aspect ratio consistent, and padding the left out areas

def letterbox_image(img, inp_dim):
	''' resize image with unchanged aspect ratio using padding '''
	img_w, img_h = img.shape[1], img.shape[0]
	w, h = inp_dim
	new_w = int(img_w * min(w/img_w, h/img_h))
	new_h = int(img_h * min(w/img_w, h/img_h))
	resized_image = cv2.resize(img, (new_w, new_h), interpolation = cv2.INTER_CUBIC)

	canvas = np.fill((inp_dim[1], inp_dim[0], 3), 128)

	canvas[(h-new_h)//2:(h-new_h)//2 + new_h], (w-new_w)//2:(w-new_w)//2 + new_w, :] = resized_image

	return canvas

# Now we write the function that takes an openCV image and converts it to the input

def prep_image(img, inp_dim):
	"""
	Prepare image for inputting to the neural network

	Returns a variable
	"""

	img = cv2.resize(img, (inp_dim, inp_dim))
	img = img[:,:,::-1].tranpose((2,0,1)).copy()
	img = torch.from_numpy(img).float().div(255.0).unsqueeze(0)
	return img 
	