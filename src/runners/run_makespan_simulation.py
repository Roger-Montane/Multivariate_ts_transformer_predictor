import sys, os, json
sys.path.append(os.path.realpath('../'))
# print(sys.path)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # INFO and WARNING messages are not printed

import numpy as np
import tensorflow as tf

from model_builds.OOPTransformer import OOPTransformer

from utilities.makespan_utils import *


MODELS_TO_RUN = [
    'FCN',
    # 'RNN',
    # 'GRU',
    # 'LSTM',
    # 'OOP_Transformer',
    # 'OOP_Transformer_small'
    ]
# MODE = 'create_data'
MODE = 'load_data'


def load_keras_model(model_name: str, makespan_models: dict, verbose: bool = True):
    try:
        model = tf.keras.models.load_model(f'../saved_models/{model_name}.keras')
        makespan_models[model_name] = model
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


def run_makespan_simulation(models_to_run: dict, data: list, confidence: float,  n_simulations: int = 100, compute: bool = True, save_dicts: bool = True):
    with open('../saved_data/makespan/makespan_results.txt', 'r') as f:
        res = json.loads(f.read())
    if compute:
        for model_name, model in models_to_run.items():
            if model_name not in res.keys():
                res[model_name] = {'metrics': {}, 'conf_mat': {}, 'times': {}, 'makespan_sim_hist': [], 'makespan_sim_avg': -1, 'makespan_sim_std': -1}
            print(f'====> For model {model_name}:')
            avg_mks, mks, metrics, conf_mat = run_simulation(
                model_name=model_name,
                model=model,
                episodes=data,
                confidence=confidence,
                n_simulations=n_simulations,
                verbose=True
            )
            if f'{model_name}_{int(confidence*100)}' not in res.keys():
                res[f'{model_name}_{int(confidence*100)}'] = {'metrics': {}, 'conf_mat': {}, 'times': {}, 'makespan_sim_hist': [], 'makespan_sim_avg': -1, 'makespan_sim_std': -1}
            res[f'{model_name}_{int(confidence*100)}']['metrics'] = metrics
            res[f'{model_name}_{int(confidence*100)}']['conf_mat'] = conf_mat
            res[f'{model_name}_{int(confidence*100)}']['makespan_sim_hist'] = mks
            res[f'{model_name}_{int(confidence*100)}']['makespan_sim_avg'] = avg_mks
            res[f'{model_name}_{int(confidence*100)}']['makespan_sim_std'] = np.std(res[model_name]['makespan_sim_hist'])
    else:
        for model_name, model in models_to_run.items():
            if f'{model_name}_{int(confidence*100)}' not in res.keys():
                res[f'{model_name}_{int(confidence*100)}'] = {'metrics': {}, 'conf_mat': {}, 'times': {}, 'makespan_sim_hist': [], 'makespan_sim_avg': -1, 'makespan_sim_std': -1}
            print(f'====> Updating expected makespan from equation for {model_name}:')
            res[model_name]['metrics']['EMS'] = abs(monitored_makespan(
                MTS=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['MTS']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['MTS'] != 'N/A' else 0,
                MTF=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['MTF']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['MTF'] != 'N/A' else 0,
                MTN=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['MTN']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['MTN'] != 'N/A' else 0,
                P_TP=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_TP']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_TP'] != 'N/A' else 0,
                P_FN=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_FN']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_FN'] != 'N/A' else 0,
                P_TN=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_TN']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_TN'] != 'N/A' else 0,
                P_FP=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_FP']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_FP'] != 'N/A' else 0,
                P_NCF=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_NCF']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_NCS'] != 'N/A' else 0,
                P_NCS=float(res[f'{model_name}_{int(confidence*100)}']['metrics']['P_NCS']) if res[f'{model_name}_{int(confidence*100)}']['metrics']['P_NCF'] != 'N/A' else 0
            ))

    print(f'res = {res}\n')

    if save_dicts:
        with open('../saved_data/makespan/makespan_results.txt', 'w') as f:
            f.write(json.dumps(res))

    return res


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
        print

    # print('LOADING MODELS...')
    # makespan_models = {}
    # if 'FCN' in MODELS_TO_RUN:
    #     load_keras_model(model_name='FCN', makespan_models=makespan_models)

    # if 'RNN' in MODELS_TO_RUN:
    #     load_keras_model(model_name='RNN', makespan_models=makespan_models)

    # if 'OOP_Transformer' in MODELS_TO_RUN:
    #     oop_transformer = OOPTransformer()
    #     num_layers = 4
    #     d_model = 6
    #     ff_dim = 256
    #     num_heads = 8
    #     head_size = 256
    #     dropout_rate = 0.2
    #     mlp_dropout = 0.4
    #     mlp_units = [128, 256, 64]

    #     oop_transformer.build(
    #         X_sample=X_train_sampled[:64],
    #         num_layers=num_layers,
    #         d_model=d_model,
    #         ff_dim=ff_dim,
    #         num_heads=num_heads,
    #         head_size=head_size,
    #         dropout_rate=dropout_rate,
    #         mlp_dropout=mlp_dropout,
    #         mlp_units=mlp_units,
    #         verbose=False
    #     )
    #     oop_transformer.compile()
    #     load_keras_weights(model_build=oop_transformer, model_name='OOP_Transformer', makespan_models=makespan_models)

    # if 'OOP_Transformer_small' in MODELS_TO_RUN:
    #     oop_transformer_small = OOPTransformer()
    #     num_layers = 4
    #     d_model = 6
    #     ff_dim = 256
    #     num_heads = 4
    #     head_size = 128
    #     dropout_rate = 0.2
    #     mlp_dropout = 0.4
    #     mlp_units = [128]

    #     oop_transformer_small.build(
    #         X_sample=X_train_sampled[:64],
    #         num_layers=num_layers,
    #         d_model=d_model,
    #         ff_dim=ff_dim,
    #         num_heads=num_heads,
    #         head_size=head_size,
    #         dropout_rate=dropout_rate,
    #         mlp_dropout=mlp_dropout,
    #         mlp_units=mlp_units,
    #         verbose=False
    #     )
    #     oop_transformer_small.compile()
    #     load_keras_weights(model_build=oop_transformer_small, model_name='OOP_Transformer_small', makespan_models=makespan_models)

    # _ = run_makespan_simulation(
    #     models_to_run=makespan_models,
    #     data_mode='load_data',
    #     compute=False
    # )