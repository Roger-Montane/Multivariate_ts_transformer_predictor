import sys, os, json
sys.path.append(os.path.realpath('../'))
# print(sys.path)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # INFO and WARNING messages are not printed

import pandas as pd
import numpy as np
import seaborn as sns
import tensorflow as tf
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnchoredText
from random import choice

from data_management.data_preprocessing import DataPreprocessing
from model_builds.FCN import FCN
from model_builds.RNN import RNN
from model_builds.VanillaTransformer import VanillaTransformer
from model_builds.OOPTransformer import OOPTransformer

from utilities.utils import CounterDict


class EpisodePerf:
    """ Container class for per-episode performance """
    def __init__( self, trueLabel = -1, answer = 'NC', runTime = float('nan'),
                  TTP = float('nan'), TTN = float('nan'), TTS = float('nan'), TTF = float('nan') ):
        self.trueLabel = trueLabel
        self.answer    = answer
        self.runTime   = runTime
        self.TTP       = TTP
        self.TTN       = TTN
        self.TTS       = TTS
        self.TTF       = TTF


def scan_output_for_decision( output, trueLabel, threshold = 0.90 ):
    for i, row in enumerate( output ):
        if np.amax( row ) >= threshold:
            if np.dot( row, trueLabel[i] ) >= threshold:
                ans = 'T'
            else:
                ans = 'F'
            if row[0] > row[1]:
                ans += 'P'
            else:
                ans += 'N'
            return ans, i, row
    return 'NC', output.shape[0], row


def expected_makespan( MTF, MTN, MTS, P_TP, P_FN, P_TN, P_FP ):
    """ Return the expected makespan for the given parameters """
    return -( MTF*P_FP + MTN*P_FN + MTN*P_TN + MTS*P_TP + 1) / (P_FN + P_FP + P_TN - 1)


def make_predictions(model_name: str, model: tf.keras.Model, dp: DataPreprocessing, verbose: bool = False):
    episode_predictions = []
    rolling_window_width = int(7.0 * 50)
    print( f"Each window is {rolling_window_width} timesteps long!" )
    for ep_index, episode in enumerate(dp.truncData):
        with tf.device('/GPU:0'):
            print(f'Episode {ep_index}')
            time_steps = episode.shape[0]
            n_windows = time_steps - rolling_window_width + 1
            episode_X_list = []
            # episode_label_list = []
            true_label = None
            for i in range(n_windows):
                # TODO: make the window centered (i.e. i +- (window_width / 2)) ??
                episode_window = episode[i:i + rolling_window_width, :]
                episode_X_list.append(episode_window[:, 1:7])

            episode_X = tf.stack(episode_X_list)
            # episode_label = tf.stack(tf.keras.utilities.to_categorical(episode_label_list, num_classes=2))
            if episode_window[0, 7] == 0.0:
                true_label = 1.0
            elif episode_window[0, 7] == 1.0:
                true_label = 0.0
            prediction = model.predict(episode_X)
            episode_predictions.append([prediction, true_label])

    np.save(f'../saved_data/epsiode_predictions/{model_name}_episode_predictions.npy', episode_predictions, allow_pickle=True)


def run_makespan_prediction_for_model(model_name: str, model: tf.keras.Model, dp: DataPreprocessing, verbose: bool = False):
    perf = CounterDict()

    N_posCls  = 0 # --------- Number of positive classifications
    N_negCls  = 0 # --------- Number of negative classifications
    N_success = 0 # --------- Number of true task successes
    N_failure = 0 # --------- Number of true task failures
    ts_s      = 20.0/1000.0 # Seconds per timestep
    MTP       = 0.0 # ------- Mean Time to Positive Classification
    MTN       = 0.0 # ------- Mean Time to Negative Classification
    MTS       = 0.0 # ------- Mean Time to Success
    MTF       = 0.0 # ------- Mean Time to Failure
    # xList     = dp.X_winTest
    # yList     = dp.Y_winTest
    # winLen    = dp.truncData[0].shape[1]

    episode_predictions = np.array(np.load(f'{model_name}_episode_predictions.npy', allow_pickle=True))
    if verbose:
        print(f'\nEpisode predictions matrix shape = {episode_predictions.shape}\n')

    timed_episodes = []

    rolling_window_width = int(7.0 * 50)
    print( f"Each window is {rolling_window_width} timesteps long!" )
    for episode in episode_predictions:
        predictions = episode[0]
        true_label = episode[1]
        n_windows = len(predictions) - rolling_window_width + 1
        n_steps = 0
        for prediction in predictions:
            ans, ad_x, row = scan_output_for_decision(
                np.array([prediction]),
                np.array([tf.keras.utils.to_categorical(true_label, num_classes=2)]),
                threshold=0.9
            )
            n_steps += 1
            if ans != 'NC':
                break

        print(f'Window {n_steps}/{n_windows}: Prediction = [{row[0]:.2f}, {row[1]:.2f}] | True label = {true_label} | Answer = {ans}')

        perf.count(ans)

        # Measure time performance
        # episode_len_s = n_steps * ts_s
        episode_len_s = (rolling_window_width + n_steps - 1) * ts_s
        # episode_len_s = (rolling_window_width + X_episodes.shape[0] - 1) * ts_s

        episode_obj = EpisodePerf()
        episode_obj.trueLabel = true_label
        episode_obj.answer = ans
        episode_obj.runTime = episode_len_s

        if true_label == 1.0:
            MTS += episode_len_s
            N_success += 1
            episode_obj.TTS = episode_len_s
        elif true_label == 0.0:
            MTF += episode_len_s
            N_failure += 1
            episode_obj.TTF = episode_len_s

        tAns_s = (ad_x + rolling_window_width - 1) * ts_s
        if ans in ( 'TP', 'FP' ):
            MTP += tAns_s
            episode_obj.TTP = tAns_s
            N_posCls += 1
        elif ans in ( 'TN', 'FN' ):
            MTN += tAns_s
            episode_obj.TTN = tAns_s
            N_negCls += 1

        timed_episodes.append(episode_obj)

    times = []
    for ep in timed_episodes:
        times.append(ep.runTime) 

    confMatx = {
        # Actual Positives
        'TP' : (perf['TP'] if ('TP' in perf) else 0) / ((perf['TP'] if ('TP' in perf) else 0) + (perf['FN'] if ('FN' in perf) else 0)),
        'FN' : (perf['FN'] if ('FN' in perf) else 0) / ((perf['TP'] if ('TP' in perf) else 0) + (perf['FN'] if ('FN' in perf) else 0)),
        # Actual Negatives
        'TN' : (perf['TN'] if ('TN' in perf) else 0) / ((perf['TN'] if ('TN' in perf) else 0) + (perf['FP'] if ('FP' in perf) else 0)),
        'FP' : (perf['FP'] if ('FP' in perf) else 0) / ((perf['TN'] if ('TN' in perf) else 0) + (perf['FP'] if ('FP' in perf) else 0)),
        'NC' : (perf['NC'] if ('NC' in perf) else 0) / len(dp.truncData),
    }

    print()
    print( perf )
    print( confMatx )

    MTP /= N_posCls #- Mean Time to Positive Classification
    MTN /= N_negCls #- Mean Time to Negative Classification
    MTS /= N_success # Mean Time to Success
    MTF /= N_failure # Mean Time to Failure

    print()
    print( f"MTP: {MTP} [s]" )
    print( f"MTN: {MTN} [s]" )
    print( f"MTS: {MTS} [s]" )
    print( f"MTF: {MTF} [s]" )
    print( f"Success: {N_success}" )
    print( f"Failure: {N_failure}" )

    if verbose:
        print('MC BASELINE...')
    N   = 200000 # Number of trials
    MTS = 0.0 # Mean time to success

    for i in range(N):
        failing = 1
        TS_i    = 0.0
        while( failing ):
            
            # Draw episode
            ep = choice( timed_episodes )
            
            # If classifier decides Negative, then we only take TTN hit but commit to another attempt
            if ep.answer[1] == 'N':
                failing = True
                TS_i += ep.TTN
            # Else we always let the episode play out and task makes decision for us
            else:
                failing = not int( ep.trueLabel )
                TS_i += ep.runTime
        MTS += TS_i
        
    MTS /= N
    print( f"\n    Task Mean Time to Success: {MTS} [s]" )


    print('    Expected makespan:', end=' ')
    EMS = expected_makespan( 
        MTF = MTF, 
        MTN = MTN, 
        MTS = MTS, 
        P_TP = confMatx['TP'] * (N_success/(N_success + N_failure)) , 
        P_FN = confMatx['FN'] * (N_success/(N_success + N_failure)) , 
        P_TN = confMatx['TN'] * (N_failure/(N_success + N_failure)) , 
        P_FP = confMatx['FP'] * (N_failure/(N_success + N_failure))  
    )
    print( EMS, end=' [s]' )
    metrics = {
        'EMS': [EMS],
        'MTP': [MTP],
        'MTN': [MTN],
        'MTS': [MTS],
        'MTF': [MTF],
        'P_TP': confMatx['TP'] * (N_success/(N_success + N_failure)),
        'P_FN': confMatx['FN'] * (N_success/(N_success + N_failure)),
        'P_TN': confMatx['TN'] * (N_failure/(N_success + N_failure)),
        'P_FP': confMatx['FP'] * (N_failure/(N_success + N_failure))
    }
    return metrics, confMatx, times


def plot_mts_ems(res: dict, save_plots: bool = True):
    mts_time_reduction = 1 - (res['VanillaTransformer']['metrics']['MTS'][0] / res['FCN']['metrics']['MTS'][0])
    mts_textstr = ''.join(f'Mean Time to Success is decreased by {mts_time_reduction*100:.2f}%\nwith VanillaTransformer')

    ems_time_reduction = 1 - (res['VanillaTransformer']['metrics']['EMS'][0] / res['FCN']['metrics']['EMS'][0])
    ems_textstr = ''.join(f'Makespan is decreased by {ems_time_reduction*100:.2f}%\nwith VanillaTransformer')

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)


    fig, axes = plt.subplots(1, 1, figsize=(20, 8))
    for model_name in res.keys():
        axes.bar([model_name], res[model_name]['metrics']['MTS'], label=model_name)

    axes.set_xlabel('Model')
    axes.set_ylabel('Mean time to Success [s]')
    axes.text(0.55, 0.75, mts_textstr, transform=axes.transAxes, alpha=0.5, bbox=props, fontsize=20)

    if save_plots:
        plt.savefig('../saved_data/imgs/makespan_prediction/mts_barplots.png')
        plt.clf()
    else:
        plt.plot()

    fig, axes = plt.subplots(1, 1, figsize=(20, 8))
    for model_name in res.keys():
        axes.bar([model_name], res[model_name]['metrics']['EMS'], alpha=0.5, label=model_name)

    # axes[1].legend()
    axes.set_xlabel('Model')
    axes.set_ylabel('Expected Makespan [s]')
    axes.text(0.55, 0.75, ems_textstr, transform=axes.transAxes, bbox=props, fontsize=20)


    if save_plots:
        plt.savefig('../saved_data/imgs/makespan_prediction/ems_barplots.png')
        plt.clf()
    else:
        plt.plot()


def plot_model_confusion_matrix(model_name: str, conf_mat: dict, save_plot: bool = True):
    arr = [
        [conf_mat['TP'], conf_mat['FP']],
        [conf_mat['FN'], conf_mat['TN']]
    ]

    sns.set(font_scale=2)
    if save_plot:
        nc_textstr = ''.join(f'{model_name} has a {conf_mat["NC"]*100:.2f}% NC rate')
        props = dict(boxstyle='round', facecolor='green', alpha=0.75)
        conf_mat_plot = sns.heatmap(arr, annot=True).get_figure()
        conf_mat_plot.text(0.43, 0.95, nc_textstr, bbox=props, fontsize=20, horizontalalignment='center', verticalalignment='top')
        conf_mat_plot.savefig(f'../saved_data/imgs/makespan_prediction/{model_name}_confusion_matrix.png')
        plt.clf()
    else:
        sns.heatmap(arr, annot=True)

    # NC percentage visualization through stacked plots
    x = ['No classification', 'Actual Positives', 'Actual negatives']
    fig, axes = plt.subplots(1, 1, figsize=(20, 8))
    if save_plot:
        nc = [conf_mat['NC'], 0, 0]
        tp = np.array([0, conf_mat['TP'], 0])
        fn = np.array([0, conf_mat['FN'], 0])
        fp = np.array([0, 0, conf_mat['FP']])
        tn = np.array([0, 0, conf_mat['TN']])
        axes.bar(x, nc, label='NC')
        axes.bar(x, tp, bottom=nc, label='TP')
        axes.bar(x, fp, bottom=nc+tp, label='FP')
        axes.bar(x, fn, bottom=nc+tp+fp, label='FN')
        axes.bar(x, tn, bottom=nc+tp+fp+fn, label='TN')
        axes.legend()
        plt.savefig(f'../saved_data/imgs/makespan_prediction/{model_name}_stacked_classification_barplots.png')
        plt.clf()
    else:
        plt.show()


def plot_runtimes(res: dict, save_plots: bool = True):
    ems_hits = np.sum([1 if vt < fcn else 0 for vt, fcn in zip(res['VanillaTransformer']['times'], res['FCN']['times'])])
    ems_performance = (ems_hits * 100) / len(res['VanillaTransformer']['times'])
    ems_textstr = ''.join(f'Runtime is lower for {ems_performance:.2f}% of the epsiodes with VanillaTransformer')

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)

    fig, axes = plt.subplots(1, 1, figsize=(20, 8))
    axes.title.set_text('Runtimes for each model')
    runtimes = []
    for model_name in res.keys():
        runtimes.append(res[model_name]['times'])
    
    axes.hist(runtimes, alpha=0.5, label=list(res.keys()), bins=10)
    axes.legend()
    axes.set_xlabel('Runtime [s]')
    axes.set_ylabel('Count')
    axes.text(0.2, 0.75, ems_textstr, transform=axes.transAxes, bbox=props, fontsize=20)

    if save_plots:
        plt.savefig('../saved_data/imgs/makespan_prediction/runtime_histogram.png')
        plt.clf()
    else:
        plt.plot()


if __name__ == '__main__':
    gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
    print( f"Found {len(gpus)} GPUs!" )
    for i in range( len( gpus ) ):
        try:
            tf.config.experimental.set_memory_growth(device=gpus[i], enable=True)
            tf.config.experimental.VirtualDeviceConfiguration( memory_limit = 1024*3 )
            print( f"\t{tf.config.experimental.get_device_details( device=gpus[i] )}" )
        except RuntimeError as e:
            print( '\n', e, '\n' )

    devices = tf.config.list_physical_devices()
    print( "Tensorflow sees the following devices:" )
    for dev in devices:
        print( f"\t{dev}" )
        print

    print('FETCHING DATA...')
    # dp = DataPreprocessing(sampling='none')
    # dp.run(verbose=True)
    dp = DataPreprocessing(sampling='none', data='reactive')
    dp.shuffle = False
    # dp.load_data(verbose=True)
    # dp.scale_data(verbose=True)
    # dp.set_episode_beginning(verbose=True)
    dp.run(save_data=False, verbose=True)

    makespan_models = {}

    # If True it will run pipeline: load models, predict (if True) and generate metrics, if False it will generate metrics from saved files
    compute = True
    # If True it will run prediction inside computation pipeline, if False it will load predictions from npy file
    predict = True
    # If True, it will save dicts upon metric generation
    save_dicts = True
    # If True it will save generated plots
    save_plots = True
    res = {}
    if compute:
        print('LOADING MODELS...')
        try:
            fcn = tf.keras.models.load_model('../saved_models/FCN.keras')
            makespan_models['FCN'] = fcn
        except OSError as e:
            print(f'{e}: model does not exist!\n')

        try:
            # vanilla_transformer = Transformer()
            # vanilla_transformer.build_model(
            #     dp.X_train_sampled.shape[1:],
            #     head_size=256,
            #     num_heads=4,
            #     ff_dim=4,
            #     num_transformer_blocks=4,
            #     mlp_units=[128],
            #     mlp_dropout=0.4,
            #     dropout=0.25
            # )
            # vanilla_transformer.model.compile(
            #     loss="binary_focal_crossentropy",
            #     optimizer=tf.keras.optimizers.Adam(learning_rate=1e-4),
            #     metrics=["categorical_accuracy"]
            # )
            # loss, accuracy_d = vanilla_transformer.model.evaluate(dp.X_test, dp.Y_test, verbose=2)
            # print("Untrained model: accuracy = {:5.2f}%; loss = {:5.2f}".format(100 * accuracy_d, loss))
            # vanilla_transformer.model.load_weights('./models/tmp/checkpoints/')
            # loss, accuracy_d = vanilla_transformer.model.evaluate(dp.X_test, dp.Y_test, verbose=2)
            # print("Restored model: accuracy = {:5.2f}%; loss = {:5.2f}".format(100 * accuracy_d, loss))
            # vanilla_transformer.model.save('../saved_models/Transformer.keras')
            vanilla_transformer =  tf.keras.models.load_model('../saved_models/Transformer.keras')
            makespan_models['VanillaTransformer'] = vanilla_transformer
        except OSError as e:
            print(f'{e}: model does not exist!\n')

        try:
            rnn = tf.keras.models.load_model('../saved_models/RNN.keras')
            makespan_models['RNN'] = rnn
        except OSError as e:
            print(f'{e}: model does not exist!\n')

        try:
            oop_transformer = OOPTransformer()
            num_layers = 8
            d_model = 6
            ff_dim = 512
            num_heads = 8
            head_size = 256
            dropout_rate = 0.25
            mlp_units = [128, 256, 64]

            oop_transformer.build(
                X_sample=dp.X_train_sampled[:32],
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
            oop_transformer.compile()
            oop_transformer.model.load_weights('../saved_models/OOP_transformer').expect_partial()
            makespan_models['OOP_Transformer'] = oop_transformer.model
        except OSError as e:
            print(f'{e}: model does not exist!')

        try:
            oop_transformer_small = OOPTransformer()
            num_layers = 4
            d_model = 6
            ff_dim = 256
            num_heads = 4
            herad_size = 128
            dropout_rate = 0.25
            mlp_units = [128]

            oop_transformer_small.build(
                X_sample=dp.X_train_sampled[:32],
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
            oop_transformer_small.compile()
            oop_transformer_small.model.load_weights('../saved_models/OOP_transformer_small').expect_partial()
            makespan_models['OOP_Transformer_small'] = oop_transformer_small.model
        except OSError as e:
            print(f'{e}: model does not exist!')


        for model_name, model in makespan_models.items():
            if model_name not in res.keys():
                res[model_name] = {'metrics': {}, 'conf_mat': {}, 'times': []}
            print(f'====> For model {model_name}:')
            if predict:
                make_predictions(model_name=model_name, model=model, dp=dp, verbose=True)
            makespan_metrics, conf_mat, times = run_makespan_prediction_for_model(model_name=model_name, model=model, dp=dp, verbose=True)
            res[model_name]['metrics'] = makespan_metrics
            res[model_name]['conf_mat'] = conf_mat
            res[model_name]['times'] = times
            print()
    else:
        with open('../saved_data/makespan/makespan_results.txt', 'r') as f:
            res = json.loads(f.read())

    print(f'res = {res}\n')

    metrics = {k: {} for k in list(res.keys())}
    for model_name in res.keys():
        metrics[model_name]['MTS_mean'] = np.mean(res[model_name]['metrics']['MTS'])
        metrics[model_name]['MTS_std'] = np.std(res[model_name]['metrics']['MTS'])

        metrics[model_name]['EMS_mean'] = np.mean(res[model_name]['metrics']['EMS'])
        metrics[model_name]['EMS_std'] = np.std(res[model_name]['metrics']['EMS'])

    if save_dicts:
        with open('../saved_data/makespan/makespan_results.txt', 'w') as f:
                f.write(json.dumps(res))

    print(f'metrics = {metrics}\n')

    plot_mts_ems(res=res, save_plots=save_plots)
    plot_runtimes(res=res, save_plots=save_plots)
    for model_name in res.keys():
        plot_model_confusion_matrix(model_name=model_name, conf_mat=res[model_name]['conf_mat'], save_plot=save_plots)