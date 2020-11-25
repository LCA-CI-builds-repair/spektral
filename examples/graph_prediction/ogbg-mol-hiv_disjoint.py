"""
This example shows how to perform molecule classification with the
[Open Graph Benchmark](https://ogb.stanford.edu) `mol-hiv` dataset, using a
simple ECC-based GNN in disjoint mode. The model does not perform really well
but should give you a starting point if you want to implement a more
sophisticated one.
"""

import numpy as np
import tensorflow as tf
from ogb.graphproppred import GraphPropPredDataset, Evaluator
from tensorflow.keras.layers import Input, Dense
from tensorflow.keras.losses import BinaryCrossentropy
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam

from spektral.data import DisjointLoader
from spektral.datasets import OGB
from spektral.layers import ECCConv, GlobalSumPool

################################################################################
# PARAMETERS
################################################################################
learning_rate = 1e-3  # Learning rate
epochs = 10           # Number of training epochs
batch_size = 32       # Batch size

################################################################################
# LOAD DATA
################################################################################
dataset_name = 'ogbg-molhiv'
ogb_dataset = GraphPropPredDataset(name=dataset_name)
dataset = OGB(ogb_dataset)

# Parameters
F = dataset.n_node_features  # Dimension of node features
S = dataset.n_edge_features  # Dimension of edge features
n_out = dataset.n_labels     # Dimension of the target

# Train/test split
idx = ogb_dataset.get_idx_split()
idx_tr, idx_va, idx_te = idx["train"], idx["valid"], idx["test"]
dataset_tr = dataset[idx_tr]
dataset_va = dataset[idx_va]
dataset_te = dataset[idx_te]

loader_tr = DisjointLoader(dataset_tr, batch_size=batch_size, epochs=epochs)
loader_te = DisjointLoader(dataset_te, batch_size=batch_size, epochs=1)

################################################################################
# BUILD MODEL
################################################################################
X_in = Input(shape=(F,))
A_in = Input(shape=(None,), sparse=True)
E_in = Input(shape=(S,))
I_in = Input(shape=(), dtype=tf.int64)

X_1 = ECCConv(32, activation='relu')([X_in, A_in, E_in])
X_2 = ECCConv(32, activation='relu')([X_1, A_in, E_in])
X_3 = GlobalSumPool()([X_2, I_in])
output = Dense(n_out, activation='sigmoid')(X_3)

# Build model
model = Model(inputs=[X_in, A_in, E_in, I_in], outputs=output)
opt = Adam(lr=learning_rate)
loss_fn = BinaryCrossentropy()


################################################################################
# FIT MODEL
################################################################################
@tf.function(
    input_signature=((tf.TensorSpec((None, F), dtype=tf.float64),
                      tf.SparseTensorSpec((None, None), dtype=tf.int64),
                      tf.TensorSpec((None, S), dtype=tf.float64),
                      tf.TensorSpec((None,), dtype=tf.int64)),
                     tf.TensorSpec((None, n_out), dtype=tf.float64)),
    experimental_relax_shapes=True)
def train_step(inputs, target):
    with tf.GradientTape() as tape:
        predictions = model(inputs, training=True)
        loss = loss_fn(target, predictions)
        loss += sum(model.losses)
    gradients = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(gradients, model.trainable_variables))
    return loss


print('Fitting model')
current_batch = 0
model_loss = 0
for batch in loader_tr:
    outs = train_step(*batch)
    model_loss += outs
    current_batch += 1
    if current_batch == loader_tr.steps_per_epoch:
        print('Loss: {}'.format(model_loss / loader_tr.steps_per_epoch))
        model_loss = 0
        current_batch = 0

################################################################################
# EVALUATE MODEL
################################################################################
print('Testing model')
evaluator = Evaluator(name=dataset_name)
y_true = []
y_pred = []
for batch in loader_te:
    inputs, target = batch
    p = model(inputs, training=False)
    y_true.append(target)
    y_pred.append(p.numpy())

y_true = np.vstack(y_true)
y_pred = np.vstack(y_pred)
model_loss = loss_fn(y_true, y_pred)
ogb_score = evaluator.eval({'y_true': y_true, 'y_pred': y_pred})

print('Done. Test loss: {:.4f}. ROC-AUC: {:.2f}'
      .format(model_loss, ogb_score['rocauc']))
