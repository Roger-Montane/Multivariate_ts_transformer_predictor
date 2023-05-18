import os, sys
sys.path.append(os.path.realpath('../'))
print( sys.version )
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # INFO and WARNING messages are not printed
import glob
import pandas as pd
import numpy as np
import tensorflow
import matplotlib.pyplot as plt
import tensorflow as tf

from tabulate import tabulate

from run_makespan_simulation import run_reactive_simulation, run_makespan_simulation
from data_management.data_preprocessing import DataPreprocessing
from model_builds.FCN import FCN
from model_builds.RNN import RNN, GRU, LSTM
from model_builds.VanillaTransformer import VanillaTransformer
from model_builds.OOPTransformer import OOPTransformer
from utilities.metrics_plots import compute_confusion_matrix
from utilities.makespan_utils import get_mts_mtf, expected_makespan, monitored_makespan, reactive_makespan, plot_simulation_makespans

SRC_PATH = os.path.dirname(os.path.realpath(__file__))
MAIN_PATH = os.path.dirname(os.path.dirname(__file__))

DATA = ['reactive', 'training']
DATA_DIR = f'../../data/data_manager/{"_".join(DATA)}'
MODELS_TO_RUN = [
    'FCN',
    'RNN',
    'GRU',
    'LSTM',
    'VanillaTransformer'
]


def load_keras_model(model_name: str, makespan_models: dict, verbose: bool = True):
    try:
        model = tf.keras.models.load_model(f'../saved_models/{model_name}.keras')
        makespan_models[model_name.split('-')[0]] = model
        if verbose:
            print(f'--> Loaded {model_name}')
    except OSError as e:
        print(f'{e}: model {model_name}.keras does not exist!\n')
    

def load_keras_weights(model_build: OOPTransformer, model_name: str, makespan_models: dict, verbose: bool = True):
    try:
        model_build.model.load_weights(f'../saved_models/{model_name}/').expect_partial()
        makespan_models[model_name] = model_build.model
        if verbose:
            print(f'--> Loaded {model_name}')
    except OSError as e:
        print(f'{e}: model weights {model_name} do not exist!')


def build_fcn(roll_win_width:int):
    # FCN
    fcn_net = FCN(rolling_window_width=roll_win_width)
    fcn_net.build()
    return fcn_net


def build_rnn():
    # RNN
    return RNN()


def build_gru():
    # GRU
    return GRU()


def build_lstm():
    # LSTM
    return LSTM()


def build_vanilla_transformer():
    # VanillaTransformer
    return VanillaTransformer()


def build_oop_transformer(X_sample, model_type: str):
    name = 'OOP_Transformer'
    if model_type == 'small':
        name = name + '_' + model_type

    transformer_net = OOPTransformer(model_name=name)

    num_layers = 4
    d_model = 6
    ff_dim = 256
    num_heads = 8
    head_size = 256
    dropout_rate = 0.2
    mlp_dropout = 0.4
    mlp_units = [128, 256, 64]
    if model_type == 'small':
        num_layers = 4
        d_model = 6
        ff_dim = 256
        num_heads = 4
        head_size = 128
        dropout_rate = 0.2
        mlp_dropout = 0.4
        mlp_units = [128]

    transformer_net.build(
            X_sample=X_sample,
            num_layers=num_layers,
            d_model=d_model,
            ff_dim=ff_dim,
            num_heads=num_heads,
            head_size=head_size,
            dropout_rate=dropout_rate,
            mlp_dropout=mlp_dropout,
            mlp_units=mlp_units,
            verbose=False
        )

    transformer_net.compile()

    return transformer_net


def get_model(name: str, roll_win_width: int = 0, X_sample = None):
    if name == 'FCN':
        return build_fcn(roll_win_width=roll_win_width)
    elif name == 'RNN':
        return build_rnn()
    elif name == 'GRU':
        return build_gru()
    elif name == 'LSTM':
        return build_lstm()
    elif name == 'VanillaTransformer':
        return build_vanilla_transformer()
    elif name == 'OOP_Transformer':
        return build_oop_transformer(X_sample=X_sample, model_type='big')
    elif name == 'OOP_Transformer_small':
        return build_oop_transformer(X_sample=X_sample, model_type='small')


def is_sub_array_contained(larger, sub):
    rows, cols = sub.shape[0], sub.shape[1]
    for i in range(len(larger) - rows + 1):
        for j in range(len(larger[0]) - cols + 1):
            if all(larger[i+k][j+l] == sub[k][l] for k in range(rows) for l in range(cols)):
                return True

    return False



if __name__ == '__main__':
    gpus = tensorflow.config.experimental.list_physical_devices(device_type='GPU')
    print( f"Found {len(gpus)} GPUs!" )
    for i in range( len( gpus ) ):
        try:
            tensorflow.config.experimental.set_memory_growth(device=gpus[i], enable=True)
            tensorflow.config.experimental.VirtualDeviceConfiguration( memory_limit = 1024*3 )
            print( f"\t{tensorflow.config.experimental.get_device_details( device=gpus[i] )}" )
        except RuntimeError as e:
            print( '\n', e, '\n' )

    devices = tensorflow.config.list_physical_devices()
    print( "Tensorflow sees the following devices:" )
    for dev in devices:
        print( f"\t{dev}" )

    # Load data
    print('\nLoading data from files...', end='')
    with open(f'{DATA_DIR}/{"_".join(DATA)}_X_train.npy', 'rb') as f:
        X_train = np.load(f, allow_pickle=True)

    # with open(f'{DATA_DIR}/{"_".join(DATA)}_Y_train.npy', 'rb') as f:
    #     Y_train = np.load(f, allow_pickle=True)

    # with open(f'{DATA_DIR}/{"_".join(DATA)}_X_test.npy', 'rb') as f:
    #     X_test = np.load(f, allow_pickle=True)

    # with open(f'{DATA_DIR}/{"_".join(DATA)}_Y_test.npy', 'rb') as f:
    #     Y_test = np.load(f, allow_pickle=True)

    with open(f'{DATA_DIR}/{"_".join(DATA)}_X_winTest.npy', 'rb') as f:
        X_window_test = np.load(f, allow_pickle=True)

    with open(f'{DATA_DIR}/{"_".join(DATA)}_Y_winTest.npy', 'rb') as f:
        Y_window_test = np.load(f, allow_pickle=True)

    with open(f'{DATA_DIR}/{"_".join(DATA)}_data.npy', 'rb') as f:
        data = np.load(f, allow_pickle=True)

    with open(f'{DATA_DIR}/{"_".join(DATA)}_data_test.npy', 'rb') as f:
        test_data = np.load(f, allow_pickle=True)

    with open(f'{DATA_DIR}/{"_".join(DATA)}_trunc_data.npy', 'rb') as f:
        trunc_data = np.load(f, allow_pickle=True)
    roll_win_width = int(7.0 * 50)
    print('DONE\n')

    # Create table to be printed
    headers = ['Measure', 'Reactive', 'FCN Simulation', 'RNN', 'GRU', 'LSTM', 'Transformer Simulation']
    data_table = [
        ['Makespan [s]', None, None, None, None, None, None],
        ['Predicted [s]', None, None, None, None, None, None],
        ['MTS', None, None, None, None, None, None],
        ['MTF', None, None, None, None, None, None]
    ]

    # Load models
    makespan_models = {}

    if 'FCN' in MODELS_TO_RUN:
        load_keras_model(model_name='FCN', makespan_models=makespan_models)

    if 'RNN' in MODELS_TO_RUN:
        load_keras_model(model_name='RNN', makespan_models=makespan_models)

    if 'GRU' in MODELS_TO_RUN:
        load_keras_model(model_name='GRU', makespan_models=makespan_models)

    if 'LSTM' in MODELS_TO_RUN:
        load_keras_model(model_name='LSTM', makespan_models=makespan_models)

    if 'VanillaTransformer' in MODELS_TO_RUN:
        load_keras_model(model_name='VanillaTransformer', makespan_models=makespan_models)

    # Call function to compute confusion matrices
    compute_conf_mats = False
    for model_name in MODELS_TO_RUN:
        model = get_model(name=model_name, roll_win_width=roll_win_width, X_sample=X_train[:64])
        model.model = makespan_models[model_name]
        if compute_conf_mats:
            _ = compute_confusion_matrix(
                model=model.model,
                file_name=model.file_name,
                imgs_path=model.imgs_path,
                X_winTest=X_window_test,
                Y_winTest=Y_window_test,
                plot=True
            )

    # TODO: match episodes in X_winTest to raw episodes, so that we only load full raw episodes (with no truncation of any kind) that belong to X_winTest
    print(f'\nTest data len = {len(test_data)}\n')

    MTS, MTF, p_success, p_failure = get_mts_mtf(data=test_data)
    r_mks = reactive_makespan(MTF=MTF, MTS=MTS, pf=p_failure, ps=p_success)
    data_table[0][1] = None
    data_table[1][1] = r_mks
    data_table[2][1] = MTS
    data_table[3][1] = MTF

    # Run simulations
    react_avg_mks, react_mks = run_reactive_simulation(
        episodes=test_data,
        n_simulations=1000,
        verbose=True
    )
    data_table[0][1] = react_avg_mks
    print()

    sim_models = {
        'FCN': makespan_models['FCN'],
        'RNN': makespan_models['RNN'],
        'GRU': makespan_models['GRU'],
        'LSTM': makespan_models['LSTM'],
        'VanillaTransformer': makespan_models['VanillaTransformer']
    }
    plot_models = {
        'FCN': makespan_models['FCN'],
        'RNN': makespan_models['RNN'],
        'GRU': makespan_models['GRU'],
        'LSTM': makespan_models['LSTM'],
        'VanillaTransformer': makespan_models['VanillaTransformer']
    }

    sim_res = run_makespan_simulation(
        models_to_run=sim_models,
        data=test_data,
        n_simulations = 150,
        data_mode='load_data',
        compute=False
    )

    plot_simulation_makespans(
        res=sim_res,
        models=plot_models,
        reactive_mks=react_mks[:150],
        plot_reactive=True,
        save_plots=True
    )

    for i, model_name in enumerate(MODELS_TO_RUN):
        data_table[0][i+2] = sim_res[model_name]['makespan_sim_avg']
        data_table[1][i+2] = sim_res[model_name]['metrics']['EMS']
        data_table[2][i+2] = sim_res[model_name]['metrics']['MTS']
        data_table[3][i+2] = sim_res[model_name]['metrics']['MTF']

    print(tabulate(data_table, headers=headers))

    # Time saving plots
    actual_react = react_avg_mks
    actual_fcn = sim_res['FCN']['makespan_sim_avg']
    actual_transformer = sim_res['VanillaTransformer']['makespan_sim_avg']

    cm_fcn = sim_res['FCN']['conf_mat']
    cm_transformer = sim_res['VanillaTransformer']['conf_mat']

    metrics_fcn = sim_res['FCN']['metrics']
    metrics_transformer = sim_res['VanillaTransformer']['metrics']

    # P_TP var independent
    n_vals = 200
    prob = np.linspace(0.0, 0.99, num=n_vals)
    result_react = [r_mks] * n_vals

    result_fcn = abs(monitored_makespan(
        MTS=metrics_fcn['MTS'],
        MTF=metrics_fcn['MTF'],
        MTN=metrics_fcn['MTN'],
        P_TP=prob,
        P_FN=metrics_fcn['P_FN'],
        P_TN=metrics_fcn['P_TN'],
        P_FP=metrics_fcn['P_FP'],
        P_NCF=metrics_fcn['P_NCF'],
        P_NCS=metrics_fcn['P_NCS']
    ))
    result_tr = abs(monitored_makespan(
        MTS=metrics_transformer['MTS'],
        MTF=metrics_transformer['MTF'],
        MTN=metrics_transformer['MTN'],
        P_TP=prob,
        P_FN=metrics_transformer['P_FN'],
        P_TN=metrics_transformer['P_TN'],
        P_FP=metrics_transformer['P_FP'],
        P_NCF=metrics_transformer['P_NCF'],
        P_NCS=metrics_transformer['P_NCS']
    ))

    plt.plot(prob, result_react, label='Reactive')
    plt.plot(metrics_fcn['P_TP'], actual_react, marker='x', color='black')

    plt.plot(prob, result_fcn, label='FCN')
    plt.plot(metrics_fcn['P_TP'], actual_fcn, marker='o', color='black')

    plt.plot(prob, result_tr, label='Transformer')
    plt.plot(metrics_transformer['P_TP'], actual_transformer, marker='o', color='gray')

    plt.plot(prob, result_react - result_fcn, label='Time saved FCN')
    plt.plot(prob, result_react - result_tr, label='Time saved Transformer')

    plt.legend()
    plt.savefig('../saved_data/imgs/simulation/sim_img_TP.png')
    plt.clf()

    result_fcn = abs(monitored_makespan(
        MTS=metrics_fcn['MTS'],
        MTF=metrics_fcn['MTF'],
        MTN=metrics_fcn['MTN'],
        P_TP=metrics_fcn['P_TP'],
        P_FN=metrics_fcn['P_FN'],
        P_TN=prob,
        P_FP=metrics_fcn['P_FP'],
        P_NCF=metrics_fcn['P_NCF'],
        P_NCS=metrics_fcn['P_NCS']
    ))
    result_tr = abs(monitored_makespan(
        MTS=metrics_transformer['MTS'],
        MTF=metrics_transformer['MTF'],
        MTN=metrics_transformer['MTN'],
        P_TP=metrics_transformer['P_TP'],
        P_FN=metrics_transformer['P_FN'],
        P_TN=prob,
        P_FP=metrics_transformer['P_FP'],
        P_NCF=metrics_transformer['P_NCF'],
        P_NCS=metrics_transformer['P_NCS']
    ))

    plt.plot(prob, result_react, label='Reactive')
    plt.plot(metrics_fcn['P_TN'], actual_react, marker='x', color='black')

    plt.plot(prob, result_fcn, label='FCN')
    plt.plot(metrics_fcn['P_TN'], actual_fcn, marker='o', color='black')

    plt.plot(prob, result_tr, label='Transformer')
    plt.plot(metrics_transformer['P_TN'], actual_transformer, marker='o', color='gray')

    plt.plot(prob, result_react - result_fcn, label='Time saved FCN')
    plt.plot(prob, result_react - result_tr, label='Time saved Transformer')

    plt.legend()
    plt.savefig('../saved_data/imgs/simulation/sim_img_TN.png')
    plt.clf()

    result_fcn = abs(monitored_makespan(
        MTS=metrics_fcn['MTS'],
        MTF=prob,
        MTN=metrics_fcn['MTN'],
        P_TP=metrics_fcn['P_TP'],
        P_FN=metrics_fcn['P_FN'],
        P_TN=metrics_fcn['P_TN'],
        P_FP=metrics_fcn['P_FP'],
        P_NCF=metrics_fcn['P_NCF'],
        P_NCS=metrics_fcn['P_NCS']
    ))
    result_tr = abs(monitored_makespan(
        MTS=metrics_transformer['MTS'],
        MTF=prob,
        MTN=metrics_transformer['MTN'],
        P_TP=metrics_transformer['P_TP'],
        P_FN=metrics_transformer['P_FN'],
        P_TN=metrics_transformer['P_TN'],
        P_FP=metrics_transformer['P_FP'],
        P_NCF=metrics_transformer['P_NCF'],
        P_NCS=metrics_transformer['P_NCS']
    ))

    plt.plot(prob, result_react, label='Reactive')
    plt.plot(metrics_fcn['MTF'], actual_react, marker='x', color='black')

    plt.plot(prob, result_fcn, label='FCN')
    plt.plot(metrics_fcn['MTF'], actual_fcn, marker='o', color='black')

    plt.plot(prob, result_tr, label='Transformer')
    plt.plot(metrics_transformer['MTF'], actual_transformer, marker='o', color='gray')

    plt.plot(prob, result_react - result_fcn, label='Time saved FCN')
    plt.plot(prob, result_react - result_tr, label='Time saved Transformer')

    plt.legend()
    plt.savefig('../saved_data/imgs/simulation/sim_img_MTF.png')
    plt.clf()

    result_fcn = abs(monitored_makespan(
        MTS=prob,
        MTF=metrics_fcn['MTF'],
        MTN=metrics_fcn['MTN'],
        P_TP=metrics_fcn['P_TP'],
        P_FN=metrics_fcn['P_FN'],
        P_TN=metrics_fcn['P_TN'],
        P_FP=metrics_fcn['P_FP'],
        P_NCF=metrics_fcn['P_NCF'],
        P_NCS=metrics_fcn['P_NCS']
    ))
    result_tr = abs(monitored_makespan(
        MTS=prob,
        MTF=metrics_transformer['MTF'],
        MTN=metrics_transformer['MTN'],
        P_TP=metrics_transformer['P_TP'],
        P_FN=metrics_transformer['P_FN'],
        P_TN=metrics_transformer['P_TN'],
        P_FP=metrics_transformer['P_FP'],
        P_NCF=metrics_transformer['P_NCF'],
        P_NCS=metrics_transformer['P_NCS']
    ))

    plt.plot(prob, result_react, label='Reactive')
    plt.plot(metrics_fcn['MTS'], actual_react, marker='x', color='black')

    plt.plot(prob, result_fcn, label='FCN')
    plt.plot(metrics_fcn['MTS'], actual_fcn, marker='o', color='black')

    plt.plot(prob, result_tr, label='Transformer')
    plt.plot(metrics_transformer['MTS'], actual_transformer, marker='o', color='gray')

    plt.plot(prob, result_react - result_fcn, label='Time saved FCN')
    plt.plot(prob, result_react - result_tr, label='Time saved Transformer')

    plt.legend()
    plt.savefig('../saved_data/imgs/simulation/sim_img_MTS.png')
    plt.clf()

