import sys, os, pickle, json
sys.path.append(os.path.realpath('../'))
# print(sys.path)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # INFO and WARNING messages are not printed

import numpy as np
import tensorflow as tf

from data_management.data_preprocessing import DataPreprocessing
from model_builds.FCN import FCN
from model_builds.RNN import RNN
from model_builds.VanillaTransformer import VanillaTransformer
from model_builds.OOPTransformer import OOPTransformer
from utilities.metrics_plots import plot_acc_loss, compute_confusion_matrix, make_probabilities_plots


DATA = 'reactive'
DATA_DIR = f'../../data/data_manager/{DATA}'
SAVE_DATA = True
LOAD_DATA_FROM_FILES = True


def run_model(model, X_train, Y_train, X_test, Y_test, X_window_test, Y_window_test, model_n_params):
    model.fit(
        X_train=X_train,
        Y_train=Y_train,
        X_test=X_test,
        Y_test=Y_test,
        epochs=200,
        save_model=True
    )
    model_n_params[model.model_name] = int(np.sum([np.prod(v.get_shape().as_list()) for v in model.model.trainable_variables]))
    plot_acc_loss(history=model.history, imgs_path=model.imgs_path)
    compute_confusion_matrix(
        model=model.model,
        file_name=model.file_name,
        imgs_path=model.imgs_path,
        X_winTest=X_window_test,
        Y_winTest=Y_window_test,
        plot=True
    )
    make_probabilities_plots(
        model=model.model,
        model_name=model.model_name,
        imgs_path=model.imgs_path,
        X_winTest=X_window_test,
        Y_winTest=Y_window_test
    )

    return model_n_params


if __name__ == '__main__':
    gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
    print( f"Found {len(gpus)} GPUs!" )
    for i in range( len( gpus ) ):
        try:
            tf.config.experimental.set_memory_growth(device=gpus[i], enable=True)
            tf.config.experimental.VirtualDeviceConfiguration( memory_limit = 1024*6 )
            print( f"\t{tf.config.experimental.get_device_details( device=gpus[i] )}" )
        except RuntimeError as e:
            print( '\n', e, '\n' )

    devices = tf.config.list_physical_devices()
    print( "Tensorflow sees the following devices:" )
    for dev in devices:
        print( f"\t{dev}" )

    dp = DataPreprocessing(sampling='none', data=DATA)
    if LOAD_DATA_FROM_FILES:
        print('\nLoading data from files...', end='')
        with open(f'{DATA_DIR}/{DATA}_X_train_sampled.npy', 'rb') as f:
            X_train_sampled = np.load(f, allow_pickle=True)

        with open(f'{DATA_DIR}/{DATA}_Y_train_sampled.npy', 'rb') as f:
            Y_train_sampled = np.load(f, allow_pickle=True)

        with open(f'{DATA_DIR}/{DATA}_X_test.npy', 'rb') as f:
            X_test = np.load(f, allow_pickle=True)

        with open(f'{DATA_DIR}/{DATA}_Y_test.npy', 'rb') as f:
            Y_test = np.load(f, allow_pickle=True)

        with open(f'{DATA_DIR}/{DATA}_X_winTest.npy', 'rb') as f:
            X_winTest = np.load(f, allow_pickle=True)

        with open(f'{DATA_DIR}/{DATA}_Y_winTest.npy', 'rb') as f:
            Y_winTest = np.load(f, allow_pickle=True)
        roll_win_width = int(7.0 * 50)
        print('DONE\n')
    else:
        print('\nCreating data with DataPreprocessng class...', end='')
        dp.run(save_data=SAVE_DATA, verbose=True)
        X_train_sampled = dp.X_train_sampled
        Y_train_sampled = dp.Y_train_sampled
        X_test = dp.X_test
        Y_test = dp.Y_test
        X_winTest = dp.X_winTest
        Y_winTest = dp.Y_winTest
        roll_win_width = dp.rollWinWidth
        print('DONE\n')

    if os.path.exists('../saved_data/model_sizes.json'):
        with open('../saved_data/model_sizes.json', 'r') as f:
            model_n_params = json.load(f)
    else:
        model_n_params = {}

    print(model_n_params)

    models_to_run = ['VanillaTransformer', 'OOP_Transformer', 'OOP_Transformer_small']

    # FCN --------------------------------------------------------
    fcn_net = FCN(rolling_window_width=roll_win_width)
    if fcn_net.model_name in models_to_run:
        fcn_net.build()
        model_n_params = run_model(
            model=fcn_net,
            X_train=X_train_sampled,
            Y_train=Y_train_sampled,
            X_test=X_test,
            Y_test=Y_test,
            X_window_test=X_winTest,
            Y_window_test=Y_winTest,
            model_n_params=model_n_params
        )

    tf.keras.backend.clear_session()
    # RNN --------------------------------------------------------
    rnn_net = RNN()
    if rnn_net.model_name in models_to_run:
        model_n_params = run_model(
            model=rnn_net,
            X_train=X_train_sampled,
            Y_train=Y_train_sampled,
            X_test=X_test,
            Y_test=Y_test,
            X_window_test=X_winTest,
            Y_window_test=Y_winTest,
            model_n_params=model_n_params
        )

    tf.keras.backend.clear_session()
    # VanillaTransformer --------------------------------------------------------
    vanilla_transformer_net = VanillaTransformer()
    if vanilla_transformer_net.model_name in models_to_run:
        model_n_params = run_model(
            model=vanilla_transformer_net,
            X_train=X_train_sampled,
            Y_train=Y_train_sampled,
            X_test=X_test,
            Y_test=Y_test,
            X_window_test=X_winTest,
            Y_window_test=Y_winTest,
            model_n_params=model_n_params
        )

        print(f'\nAttention scores:\n{vanilla_transformer_net.last_attn_scores}\n')

    tf.keras.backend.clear_session()
    # OOP Transformer --------------------------------------------------------
    transformer_net = OOPTransformer()
    if transformer_net.model_name in models_to_run:
        num_layers = 8
        d_model = 6
        ff_dim = 512
        num_heads = 8
        head_size = 256
        dropout_rate = 0.25
        mlp_units = [128, 256, 64]

        transformer_net.build(
            X_sample=X_train_sampled[:32],
            num_layers=num_layers,
            d_model=d_model,
            ff_dim=ff_dim,
            num_heads=num_heads,
            head_size=head_size,
            dropout_rate=dropout_rate,
            mlp_units=mlp_units,
            save_model=True,
            verbose=True
        )

        transformer_net.compile()
        model_n_params = run_model(
            model=transformer_net,
            X_train=X_train_sampled,
            Y_train=Y_train_sampled,
            X_test=X_test,
            Y_test=Y_test,
            X_window_test=X_winTest,
            Y_window_test=Y_winTest,
            model_n_params=model_n_params
        )

    tf.keras.backend.clear_session()
    # OOP Transformer (Small) --------------------------------------------------------
    transformer_net_small = OOPTransformer(model_name='OOP_Transformer_small')
    if transformer_net_small.model_name in models_to_run:
        num_layers = 4
        d_model = 6
        ff_dim = 256
        num_heads = 4
        herad_size = 128
        dropout_rate = 0.25
        mlp_units = [128]

        transformer_net_small.build(
            X_sample=X_train_sampled[:32],
            num_layers=num_layers,
            d_model=d_model,
            ff_dim=ff_dim,
            num_heads=num_heads,
            head_size=head_size,
            dropout_rate=dropout_rate,
            mlp_units=mlp_units,
            save_model=True,
            verbose=True
        )

        transformer_net_small.compile()

        model_n_params = run_model(
            model=transformer_net_small,
            X_train=X_train_sampled,
            Y_train=Y_train_sampled,
            X_test=X_test,
            Y_test=Y_test,
            X_window_test=X_winTest,
            Y_window_test=Y_winTest,
            model_n_params=model_n_params
        )

    with open('../saved_data/model_sizes.json', 'w') as f:
        json.dump(model_n_params, f)
