import os, sys, inspect, time
# This example requires theano & lasagne
import theano
import theano.tensor as T
import lasagne
import numpy as np

"""
Make the lib available here
"""
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

from mince.database_builder import HDF5ClassDatabaseBuilder
from mince.database_reader import HDF5DatabaseReader
from mince.multiprocess import MultiProcessor
from mince.networks import resnet_50


"""
Preprocessor function
"""


def process(images, labels):
    images = images.astype(theano.config.floatX)
    images[:, 0, :, :] -= 142.9
    images[:, 1, :, :] -= 115.7
    images[:, 2, :, :] -= 89.52

    return images, labels


"""
Main program
"""
if __name__ == "__main__":
    """
    Mince part
    """
    print "Building database"

    # Target db location prefix
    db = '/Users/sebastian/Desktop/mince'

    # Folder holding subfolders, one for each class
    folder = '/Users/sebastian/Desktop/mince_data_small'

    # Use helper to parse the folder
    classes = HDF5ClassDatabaseBuilder.parse_folder(folder)
    n_classes = len(classes)

    # Build a db from a set of images
    # In case force=false, we do not recreate the db if it's already there!
    train_db, val_db = HDF5ClassDatabaseBuilder.build(db, folder, shape=(224, 224), force=False)

    # Batch size to use during training
    batch_size = 1
    # Prepare the training reader for read access. This is necessary when combining it with multiprocessors
    train_reader = HDF5DatabaseReader()
    train_reader.setup_read(train_db, randomize_access=True)
    # Create a multiprocessor object which manages data loading and transformation daemons
    train_processor = MultiProcessor(train_reader, func=process, batch_size=batch_size)
    # Start the daemons and tell them to use the databuilder we just setup to pull data from disk
    train_processor.start_daemons()

    # We also need to read validation data. It's way less so we just do in in the main thread
    # and don't start any daemons
    val_reader = HDF5DatabaseReader()
    val_reader.setup_read(val_db)
    val_processor = MultiProcessor(val_reader, batch_size=batch_size)

    """
    Lasagne part
    """
    print "Building and compiling network"
    # Prepare Theano variables for inputs and targets
    input_var = T.tensor4('inputs')

    # Careful. We feed one-hot coded labels
    target_var = T.imatrix('targets')
    network = resnet_50(input_var, n_classes)

    prediction = lasagne.layers.get_output(network)
    loss = lasagne.objectives.categorical_crossentropy(prediction, target_var)
    loss = loss.mean()

    # add weight decay
    all_layers = lasagne.layers.get_all_layers(network)
    l2_penalty = lasagne.regularization.regularize_layer_params(all_layers, lasagne.regularization.l2) * 0.0001
    loss = loss + l2_penalty

    params = lasagne.layers.get_all_params(network, trainable=True)
    updates = lasagne.updates.nesterov_momentum(
        loss, params, learning_rate=0.001, momentum=0.9)

    # Create a loss expression for validation/testing. The crucial difference
    # here is that we do a deterministic forward pass through the network,
    # disabling dropout layers.
    test_prediction = lasagne.layers.get_output(network, deterministic=True)
    test_loss = lasagne.objectives.categorical_crossentropy(test_prediction,
                                                            target_var)
    test_loss = test_loss.mean()
    # As a bonus, also create an expression for the classification accuracy:
    test_acc = T.mean(T.eq(T.argmax(test_prediction, axis=1), T.argmax(target_var, axis=1)),
                      dtype=theano.config.floatX)

    # Compile a function performing a training step on a mini-batch (by giving
    # the updates dictionary) and returning the corresponding training loss:
    train_fn = theano.function([input_var, target_var], loss, updates=updates)

    # Compile a second function computing the validation loss and accuracy:
    val_fn = theano.function([input_var, target_var], [test_loss, test_acc, test_prediction])

    """
    Training procedure
    """
    print "Starting training"

    n_epochs = 50

    for epoch in range(n_epochs):
        # In each epoch, we do a full pass over the training data:
        train_err = 0
        train_batches = 0
        start_time = time.time()
        for batch in train_processor.iterate():
            inputs, targets = batch
            print inputs.mean()
            err = train_fn(inputs, targets)
            print err
            train_err += err
            train_batches += 1

        # And a full pass over the validation data:
        val_err = 0
        val_acc = 0
        val_batches = 0
        for batch in val_processor.iterate():
            inputs, targets = batch
            err, acc, pred = val_fn(inputs, targets)
            val_err += err
            val_acc += acc
            val_batches += 1

        # Then we print the results for this epoch:
        print("Epoch {} of {} took {:.3f}s".format(
            epoch + 1, n_epochs, time.time() - start_time))
        print("  training loss:\t\t{:.6f}".format(train_err / train_batches))
        print("  validation loss:\t\t{:.6f}".format(val_err / val_batches))
        print("  validation accuracy:\t\t{:.2f} %".format(val_acc / val_batches * 100))
