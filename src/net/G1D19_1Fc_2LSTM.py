import tensorflow as tf
from src.net.NetBase import *
from src.layers.BasicLayers import *
from src.layers.RNN import *
import settings.LayerSettings as layerSettings
import settings.DataSettings as dataSettings
import numpy as np

DARKNET19_MODEL_PATH = 'data/pretrainModels/darknet19/darknet19.pb'

class Net(NetworkBase):
	def __init__(self, inputImage_, batchSize_, unrolledSize_, isTraining_, trainingStep_):
		self._inputImage = inputImage_
		self._batchSize = batchSize_
		self._unrolledSize = unrolledSize_
		self._isTraining = isTraining_
		self._trainingStep = trainingStep_
	
		self._DROPOUT_VALUE = 0.5
		self._NUMBER_OF_NEURONS_IN_LSTM = 512

		self._dictOfInterestedActivations = {}

		if dataSettings.GROUPED_SIZE != 1:
			errorMessage = __name__ + " only take GROUPED_SIZE = 1;\n"
			errorMessage += "However, DataSettings.GROUPED_SIZE = " + str(dataSettings.GROUPED_SIZE)
			raise ValueError(errorMessage)

	def Build(self):
		darknet19_GraphDef = tf.GraphDef()

		'''
		      The CNN only take input shape [..., w, h, c].  Thus, move the UNROLLED_SIZE dimension
		    to merged with BATCH_SIZE, and form the shape: [b*u, w, h, c].
		'''
		convInput = tf.reshape(self._inputImage, [-1,
							  dataSettings.IMAGE_SIZE, dataSettings.IMAGE_SIZE, dataSettings.IMAGE_CHANNELS])

		with tf.name_scope("DarkNet19"):
			with open(DARKNET19_MODEL_PATH, 'rb') as modelFile:
				darknet19_GraphDef.ParseFromString(modelFile.read())
				listOfOperations = tf.import_graph_def(darknet19_GraphDef,
									input_map={"input": convInput},
									return_elements=["BiasAdd_13"])
#									return_elements=["32-leaky"])
#									return_elements=["BiasAdd_14"])
#									return_elements=["34-leaky"])
#									return_elements=["BiasAdd_15"])
#									return_elements=["36-leaky"])
#									return_elements=["BiasAdd_16"])
#									return_elements=["38-leaky"])
#									return_elements=["BiasAdd_17"])
#									return_elements=["40-leaky"])
#									return_elements=["Pad_18"])
#									return_elements=["41-convolutional"])
#									return_elements=["BiasAdd_18"])
				lastOp = listOfOperations[-1]
				darknetOutput = lastOp.outputs[0]
			
		with tf.name_scope("Fc_ConcatPair"):
			out = FullyConnectedLayer('Fc1', darknetOutput, numberOfOutputs_=2048)
			out, updateVariablesOp1 = BatchNormalization('BN1', out, isConvLayer_=False,
								     isTraining_=self._isTraining, currentStep_=self._trainingStep)
			'''
			    Note: For tf.nn.rnn_cell.dynamic_rnn(), the input shape of [1:] must be explicit.
			          i.e., one Can't Reshape the out by:
				  out = tf.reshape(out, [BATCH_SIZE, UNROLLED_SIZE, -1])
				  since '-1' is implicit dimension.
			'''
			featuresShapeInOneBatch = out.shape[1:].as_list()
			targetShape = [self._batchSize, self._unrolledSize] + featuresShapeInOneBatch
			out = tf.reshape(out, targetShape)

		out, self._stateTensorOfLSTM_1, self._statePlaceHolderOfLSTM_1 = LSTM(	"LSTM_1",
											out,
											self._NUMBER_OF_NEURONS_IN_LSTM,
											isTraining_=self._isTraining,
											dropoutProb_=0.5)

		out, self._stateTensorOfLSTM_2, self._statePlaceHolderOfLSTM_2 = LSTM(	"LSTM_2",
											out,
											self._NUMBER_OF_NEURONS_IN_LSTM,
											isTraining_=self._isTraining,
											dropoutProb_=0.5)



		with tf.name_scope("Fc_Final"):
			featuresShapeInOneBatch = out.shape[2:].as_list()
			targetShape = [self._batchSize * self._unrolledSize] + featuresShapeInOneBatch
			out = tf.reshape(out, targetShape)
			out = FullyConnectedLayer('Fc3', out, numberOfOutputs_=dataSettings.NUMBER_OF_CATEGORIES)
			self._logits = tf.reshape(out, [self._batchSize, self._unrolledSize, -1])

		self._updateOp = tf.group(updateVariablesOp1)

	@property
	def logitsOp(self):
		return self._logits

	@property
	def updateOp(self):
		return self._updateOp


	def GetListOfStatesTensorInLSTMs(self):
		'''
		    You should Not Only sess.run() the net.logits, but also this listOfTensors
		    to get the States of LSTM.  And assign it to PlaceHolder next time.
		    ex:
			>> tupleOfResults = sess.run( [out] + net.GetListOfStatesTensorInLSTMs(), ...)
			>> listOfResults = list(tupleOfResults)
			>> output = listOfResults.pop(0)
			>> listOfStates = listOfResults

		    See GetFeedDictOfLSTM() method as well
		'''
		return [ self._stateTensorOfLSTM_1, self._stateTensorOfLSTM_2 ]


	def GetFeedDictOfLSTM(self, BATCH_SIZE_, listOfPreviousStateValues_=None):
		'''
		      This function will return a dictionary that contained the PlaceHolder-Value map
		    of the LSTM states.
		      You can use this function as follows:
		    >> feed_dict = { netInput : batchOfImages }
		    >> feedDictOFLSTM = net.GetLSTM_Feed_Dict(BATCH_SIZE, listOfPreviousStateValues)
		    >> tupleOfOutputs = sess.run( [out] + net.GetListOfStatesTensorInLSTMs(),
						  feed_dict = feed_dict.update(feedDictOFLSTM) ) 
		    >> listOfOutputs = list(tupleOfOutputs)
		    >> output = listOfOutputs.pop(0)
		    >> listOfPreviousStateValues = listOfOutputs.pop(0)
		'''
		if listOfPreviousStateValues_ == None:
			'''
			    For the first time (or, the first of Unrolls), there's no previous state,
			    return zeros state.
			'''
			initialStateOfLSTM_1 = tuple( [np.zeros([BATCH_SIZE_, self._NUMBER_OF_NEURONS_IN_LSTM])] * 2 )
			initialStateOfLSTM_1 = tf.nn.rnn_cell.LSTMStateTuple(initialStateOfLSTM_1[0], initialStateOfLSTM_1[1])

			initialStateOfLSTM_2 = tuple( [np.zeros([BATCH_SIZE_, self._NUMBER_OF_NEURONS_IN_LSTM])] * 2 )
			initialStateOfLSTM_2 = tf.nn.rnn_cell.LSTMStateTuple(initialStateOfLSTM_2[0], initialStateOfLSTM_2[1])

			return { self._statePlaceHolderOfLSTM_1 : initialStateOfLSTM_1,
				 self._statePlaceHolderOfLSTM_2 : initialStateOfLSTM_2 }
		else:
			if len(listOfPreviousStateValues_) != 2:
				errorMessage = "len(listOfPreviousStateValues_) = " + str( len(listOfPreviousStateValues_) )
				errorMessage += "; However, the expected lenght is 2.\n"
				errorMessage += "\t Do you change the Network Structure, such as Add New LSTM?\n"
				errorMessage += "\t Or, do you add more tensor to session.run()?\n"

			return { self._statePlaceHolderOfLSTM_1 : listOfPreviousStateValues_[0],
				 self._statePlaceHolderOfLSTM_2 : listOfPreviousStateValues_[1] }

