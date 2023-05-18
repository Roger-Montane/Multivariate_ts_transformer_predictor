import sys, os, json
import random
sys.path.append(os.path.realpath('../'))
# print(sys.path)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # INFO and WARNING messages are not printed

import numpy as np
import seaborn as sns
import tensorflow as tf
import matplotlib.pyplot as plt

from random import choice
from data_management.data_preprocessing import DataPreprocessing
from utilities.utils import CounterDict, set_size

# Classes --------------------------------------------------------------------------
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

# Functions -----------------------------------------------------------------------
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


def monitored_makespan( MTS, MTF, MTN, P_TP, P_FN, P_TN, P_FP, P_NCS, P_NCF ):
    """ Closed form makespan for monitored case, symbolic simplification from Mathematica """
    return (1 + MTF*(P_FP + P_NCF) + MTS*(P_NCS + P_TP) + MTN*(P_FN + P_TN) ) / (1 - P_FN - P_FP - P_TN)

def monitored_makespan_alternative( MTS, MTF, MTN, P_TP, P_FN, P_TN, P_FP, P_NCS, P_NCF ):
    """ Closed form makespan for monitored case, symbolic simplification from Mathematica """
    return (1 + MTF*(P_FP + P_NCF) + MTS*(P_NCS + P_TP) + MTF*(P_FN + P_TN) ) / (1 - P_FN - P_FP - P_TN)

def reactive_makespan(MTS, MTF, ps, pf):
    return -(MTF * pf + MTS * ps + 1) / (pf - 1)


def get_mts_mtf(data: list):
    MTS = 0
    MTF = 0
    N_success = 0
    N_failure = 0
    ts_s      = 20.0/1000.0
    rolling_window_width = int(7.0 * 50)
    for ep_index, episode in enumerate(trunc_data):
        episode_len_s = episode.shape[0] * ts_s
        raw_label = episode[0:rolling_window_width, :][0, 7]
        if raw_label == 0.0:
            MTF += episode_len_s
            N_failure += 1
        elif raw_label == 1.0:
            MTS += episode_len_s
            N_success += 1

    MTS /= N_success # Mean Time to Success
    MTF /= N_failure # Mean Time to Failure

    return MTS, MTF, N_success/len(trunc_data), N_failure/len(trunc_data)


def make_predictions(model_name: str, model: tf.keras.Model, trunc_data, verbose: bool = False):
    episode_predictions = []
    rolling_window_width = int(7.0 * 50)
    print( f"Each window is {rolling_window_width} timesteps long!" )
    for ep_index, episode in enumerate(trunc_data):
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
            prediction = model.predict(episode_X, use_multiprocessing=True)
            episode_predictions.append([prediction, true_label])

    np.save(f'../saved_data/episode_predictions/{model_name}_episode_predictions.npy', episode_predictions, allow_pickle=True)



def classify(model: tf.keras.Model, episode: np.ndarray, true_label: float, window_width: int, ts_s: float = 20.0/1000.0):
    with tf.device('/GPU:0'):
        time_steps = episode.shape[0]
        n_windows = time_steps - window_width + 1
        episode_X_list = []
        for i in range(n_windows):
            if i >= window_width:
                # episode_window = episode[i:i + window_width, :]
                episode_window = episode[i - window_width:i, :]
                episode_X_list.append(episode_window[:, 1:7])
        episode_X = tf.stack(episode_X_list)
        prediction = model.predict(episode_X, use_multiprocessing=True)
        ans, t_c, row = scan_output_for_decision(
            np.array(prediction),
            np.array([tf.keras.utils.to_categorical(true_label, num_classes=2)] * len(prediction)),
            threshold=0.9
        )

    # Return the classification answer and the time (in seconds) at which the classification happened
    return ans, (window_width * ts_s) + (t_c * ts_s)


def run_reactive_simulation(episodes: list, n_simulations: int = 100, verbose: bool = False):
    total_time = 0
    mks = []
    for i in range(n_simulations):
        if verbose:
            # print(f'Simulation {i+1}/{n_simulations}:')
            sys.stdout.write("\rSimulation %d/%d" % (i+1, n_simulations))
            sys.stdout.flush()
        win = False
        makespan = 0
        while not win:
            ep = random.choice(episodes)
            episode_time = ep.shape[0] * (20.0 / 1000.0)
            true_label = 0.0
            if ep[0, 7] == 0.0:
                true_label = 1.0
            # If true_label == failure
            if true_label == 1.0:
                makespan += episode_time
            # If true_label == success
            elif true_label == 0.0:
                makespan += episode_time
                win = True
        total_time += makespan
        mks.append(makespan)
    return total_time / n_simulations, mks


def run_simulation(model: tf.keras.Model, episodes: list, n_simulations: int = 1000, verbose: bool = False):
    perf = CounterDict()
    N_posCls  = 0 # --------- Number of positive classifications
    N_negCls  = 0 # --------- Number of negative classifications
    N_success = 0 # --------- Number of true task successes
    N_failure = 0 # --------- Number of true task failures
    MTP       = 0.0 # ------- Mean Time to Positive Classification
    MTN       = 0.0 # ------- Mean Time to Negative Classification
    MTS       = 0.0 # ------- Mean Time to Success
    MTF       = 0.0 # ------- Mean Time to Failure

    timed_episodes = []
    rolling_window_width = int(7.0 * 50)
    ts_s = 20.0 / 1000.0
    total_time = 0
    mks = []

    # Params for selecting first F_z hit
    winWidth    = 10
    FzCol       =  3
    spikeThresh = 0.05

    for i in range(n_simulations):
        if verbose:
            print(f'Simulation {i+1}/{n_simulations}:')
        win = False
        makespan = 0
        while not win:
            ep = random.choice(episodes)
            episode_time = ep.shape[0] * ts_s
            N = ep.shape[0]
            chopDex = 0
            for bgn in range( int(1.5*50), N-winWidth+1 ):
                end     = bgn+winWidth
                FzSlice = ep[ bgn:end, FzCol ].flatten()
                if np.abs( np.amax( FzSlice ) - np.amin( FzSlice ) ) >= spikeThresh:
                    chopDex = end
                    break
            if (chopDex * ts_s) < 15.0:
                ep_matrix = ep[chopDex:, :]
                true_label = 0.0
                if ep_matrix[0, 7] == 0.0:
                    true_label = 1.0
                ans, t_c = classify(
                    model=model,
                    episode=ep_matrix,
                    true_label=true_label,
                    window_width=rolling_window_width,
                    ts_s=ts_s
                )

                episode_obj = EpisodePerf()
                episode_obj.trueLabel = true_label
                episode_obj.answer = ans
                episode_obj.runTime = episode_time

                if ans == 'NC':
                    if true_label == 1.0:
                        makespan += episode_time
                        perf.count('NCF')
                    elif true_label == 0.0:
                        makespan += episode_time
                        win = True
                        perf.count('NCS')
                else:
                    perf.count(ans)
                    if ans in ('TN', 'FN'):
                        makespan += t_c + (chopDex * ts_s)
                        MTN += t_c + (chopDex * ts_s)
                        episode_obj.TTN = t_c + (chopDex * ts_s)
                        N_negCls += 1
                    elif ans in ('TP', 'FP'):
                        makespan += episode_time
                        win = True
                        MTP += episode_time
                        episode_obj.TTP = episode_time
                        N_posCls += 1

                if true_label == 1.0:
                    MTF += episode_time
                    N_failure += 1
                elif true_label == 0.0:
                    MTS += episode_time
                    N_success += 1

                timed_episodes.append(episode_obj)
        total_time += makespan
        mks.append(makespan)

    confMatx = {
        # Actual Positives
        'TP' : (perf['TP'] if ('TP' in perf) else 0) / ((perf['TP'] if ('TP' in perf) else 0) + (perf['FN'] if ('FN' in perf) else 0)),
        'FN' : (perf['FN'] if ('FN' in perf) else 0) / ((perf['TP'] if ('TP' in perf) else 0) + (perf['FN'] if ('FN' in perf) else 0)),
        # Actual Negatives
        'TN' : (perf['TN'] if ('TN' in perf) else 0) / ((perf['TN'] if ('TN' in perf) else 0) + (perf['FP'] if ('FP' in perf) else 0)),
        'FP' : (perf['FP'] if ('FP' in perf) else 0) / ((perf['TN'] if ('TN' in perf) else 0) + (perf['FP'] if ('FP' in perf) else 0)),
        'NC' : (perf['NCS'] + perf['NCF'] if ('NCS' in perf and 'NCF' in perf) else 0) / len(timed_episodes),
    }

    MTP /= N_posCls #- Mean Time to Positive Classification
    MTN /= N_negCls #- Mean Time to Negative Classification
    MTS /= N_success
    MTF /= N_failure
    # MTS, MTF, _, _ = get_mts_mtf(trunc_data=episodes)

    print( f"MTP: {MTP} [s]" )
    print( f"MTN: {MTN} [s]" )
    print( f"MTS: {MTS} [s]" )
    print( f"MTF: {MTF} [s]" )

    if MTN >= MTF:
        EMS = abs(monitored_makespan_alternative(
            MTF = MTF,
            MTN = MTN,
            MTS = MTS,
            P_TP = perf['TP'] / len(timed_episodes),
            P_FN = perf['FN'] / len(timed_episodes),
            P_TN = perf['TN'] / len(timed_episodes),
            P_FP = perf['FP'] / len(timed_episodes),
            P_NCS = perf['NCS'] / len(timed_episodes),
            P_NCF = perf['NCF'] / len(timed_episodes)
        ))
    else:
        EMS = abs(monitored_makespan(
            MTF = MTF,
            MTN = MTN,
            MTS = MTS,
            P_TP = perf['TP'] / len(timed_episodes),
            P_FN = perf['FN'] / len(timed_episodes),
            P_TN = perf['TN'] / len(timed_episodes),
            P_FP = perf['FP'] / len(timed_episodes),
            P_NCS = perf['NCS'] / len(timed_episodes),
            P_NCF = perf['NCF'] / len(timed_episodes)
        ))

    print('Expected makespan [s] = ', end='')
    print( EMS, end=' [s]\n' )
    metrics = {
        'EMS': EMS,
        'MTP': MTP,
        'MTN': MTN,
        'MTS': MTS,
        'MTF': MTF,
        'P_TP': perf['TP'] / len(timed_episodes),
        'P_FN': perf['FN'] / len(timed_episodes),
        'P_TN': perf['TN'] / len(timed_episodes),
        'P_FP': perf['FP'] / len(timed_episodes),
        'P_NCS': perf['NCS'] / len(timed_episodes),
        'P_NCF': perf['NCF'] / len(timed_episodes)
    }

    return total_time / n_simulations, mks, metrics, confMatx


# TODO: fix this function, something wrong with MTP, MTN, MTS, MTF
def run_makespan_prediction_for_model(model_name: str, verbose: bool = False):
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

    episode_predictions = np.array(np.load(f'../saved_data/episode_predictions/{model_name}_episode_predictions.npy', allow_pickle=True))
    if verbose:
        print(f'\nEpisode predictions matrix shape = {episode_predictions.shape}\n')

    timed_episodes = []

    rolling_window_width = int(7.0 * 50)
    print( f"Each window is {rolling_window_width} timesteps long!" )
    for episode in episode_predictions:
        predictions = episode[0]
        true_label = episode[1]
        n_windows = len(predictions)
        episode_len_s = (n_windows + rolling_window_width - 1) * ts_s
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

        # perf.count(ans)
        if ans == 'NC':
            if true_label == 0.0:
                perf.count('NCS')
            elif true_label == 1.0:
                perf.count('NCF')
        else:
            perf.count(ans)

        # episode len = number of rows of episode:
        # episode_len_s = N_rows * ts_s
        # episode_len_s = (rolling_window_width + n_steps - 1) * ts_s
        # episode_len_s = (rolling_window_width + X_episodes.shape[0] - 1) * ts_s

        episode_obj = EpisodePerf()
        episode_obj.trueLabel = true_label
        episode_obj.answer = ans
        episode_obj.runTime = episode_len_s

        tAns_s = (rolling_window_width + n_steps - 1) * ts_s
        if ans in ( 'TP', 'FP' ):
            MTP += tAns_s
            episode_obj.TTP = tAns_s
            N_posCls += 1
        elif ans in ( 'TN', 'FN' ):
            MTN += tAns_s
            episode_obj.TTN = tAns_s
            N_negCls += 1


        if true_label == 0.0:
            MTS += episode_len_s
            N_success += 1
            episode_obj.TTS = episode_len_s
        elif true_label == 1.0:
            MTF += episode_len_s
            N_failure += 1
            episode_obj.TTF = episode_len_s

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
        'NC' : (perf['NCS'] + perf['NCF'] if ('NCS' in perf and 'NCF' in perf) else 0) / len(episode_predictions),
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
        print('MC MONITORED BASELINE...')


    N   = 200000 # Number of trials
    MTS = 0.0 # Mean time to success

    print( f"Sampling {N} episodes from {len(timed_episodes)} trials" )

    for i in range(N):
        failing = 1
        TS_i    = 0.0
        while( failing ):

            # Draw episode
            ep = choice(timed_episodes)

            # If classifier decides Negative, then we only take TTN hit but commit to another attempt
            if ep.answer[-1] == 'N':
                failing = True
                TS_i += ep.TTN
                # if i%int(N/10) == 0:
                #     print( ep.TTN )
            # Else we always let the episode play out and task makes decision for us
            elif ep.answer[-1] == 'P':
                failing = not int(ep.trueLabel)
                TS_i += ep.runTime
            else:
                failing = not int(ep.trueLabel)
                TS_i += ep.runTime
        MTS += TS_i
        
    MTS /= N
    print( f"    Task Mean Time to Success: {MTS} [s]" )


    print('    Expected makespan:', end=' ')
    # EMS = expected_makespan( 
    #     MTF = MTF, 
    #     MTN = MTN, 
    #     MTS = MTS, 
    #     P_TP = confMatx['TP'] * (N_success/(N_success + N_failure)) , 
    #     P_FN = confMatx['FN'] * (N_success/(N_success + N_failure)) , 
    #     P_TN = confMatx['TN'] * (N_failure/(N_success + N_failure)) , 
    #     P_FP = confMatx['FP'] * (N_failure/(N_success + N_failure))  
    # )
    EMS = monitored_makespan(
        MTF = MTF, 
        MTN = MTN, 
        MTS = MTS,
        P_TP = confMatx['TP'] / len(episode_predictions), 
        P_FN = confMatx['FN'] / len(episode_predictions), 
        P_TN = confMatx['TN'] / len(episode_predictions), 
        P_FP = confMatx['FP'] / len(episode_predictions),
        P_NCS = perf['NCS'] / len(episode_predictions),
        P_NCF = perf['NCF'] / len(episode_predictions)
    )
    print( EMS, end=' [s]\n' )
    metrics = {
        'EMS': [EMS],
        'MTP': [MTP],
        'MTN': [MTN],
        'MTS': [MTS],
        'MTF': [MTF],
        'P_TP': confMatx['TP'] / len(episode_predictions), 
        'P_FN': confMatx['FN'] / len(episode_predictions), 
        'P_TN': confMatx['TN'] / len(episode_predictions), 
        'P_FP': confMatx['FP'] / len(episode_predictions),
        'P_NCS': perf['NCS'] / len(episode_predictions),
        'P_NCF': perf['NCF'] / len(episode_predictions)
    }
    return metrics, confMatx, times


# Plotting ----------------------------------------------------------------------------
def plot_mts_ems(res: dict, models_to_use: list, save_plots: bool = True):
    # Setup
    # plt.style.use('seaborn')
    # From Latex \textwidth
    fig_width = 800
    tex_fonts = {
        # Use LaTeX to write all text
        # "text.usetex": True,
        "font.family": "serif",
        # Use 10pt font in plots, to match 10pt font in document
        "axes.labelsize": 14,
        "font.size": 14,
        # Make the legend/label fonts a little smaller
        "legend.fontsize": 12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12
    }
    plt.rcParams.update(tex_fonts)

    mts_time_reduction = 1 - (res['VanillaTransformer']['metrics']['MTS'][0] / res['FCN']['metrics']['MTS'][0])
    mts_textstr = ''.join(f'Mean Time to Success is decreased by {mts_time_reduction*100:.2f}%\nwith Transformer')

    ems_time_reduction = 1 - (res['VanillaTransformer']['metrics']['EMS'][0] / res['FCN']['metrics']['EMS'][0])
    ems_textstr = ''.join(f'Makespan is decreased by {ems_time_reduction*100:.2f}%\nwith Transformer')

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)


    fig, axes = plt.subplots(1, 1, figsize=set_size(fig_width))
    # fig.tight_layout()
    for model_name in res.keys():
        if model_name in models_to_use:
            axes.bar([model_name], res[model_name]['metrics']['MTS'], label=model_name)

    axes.set_xlabel('Model')
    axes.set_ylabel('Mean time to Success [s]')
    axes.text(0.55, 0.75, mts_textstr, transform=axes.transAxes, alpha=0.5, bbox=props, fontsize=20)

    if save_plots:
        plt.savefig('../saved_data/imgs/makespan_prediction/mts_barplots.png')
        plt.clf()
    else:
        plt.plot()

    fig, axes = plt.subplots(1, 1, figsize=set_size(fig_width))
    # fig.tight_layout()
    for model_name in res.keys():
        if model_name in models_to_use:
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
    # Setup
    # plt.style.use('seaborn')
    # From Latex \textwidth
    fig_width = 600
    tex_fonts = {
        # Use LaTeX to write all text
        # "text.usetex": True,
        "font.family": "serif",
        # Use 10pt font in plots, to match 10pt font in document
        "axes.labelsize": 14,
        "font.size": 14,
        # Make the legend/label fonts a little smaller
        "legend.fontsize": 12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12
    }
    plt.rcParams.update(tex_fonts)

    arr = [
        [conf_mat['TP'], conf_mat['FP']],
        [conf_mat['FN'], conf_mat['TN']]
    ]

    sns.set(font_scale=2)
    if save_plot:
        if model_name == 'VanillaTransformer':
            nc_textstr = ''.join(f'Transformer has a {conf_mat["NC"]*100:.2f}% NC rate')
        else:
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
    fig, axes = plt.subplots(1, 1, figsize=set_size(fig_width))
    fig.tight_layout()
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


def plot_runtimes(res: dict, models_to_use: list, save_plots: bool = True):
    # Setup
    # plt.style.use('seaborn')
    # From Latex \textwidth
    fig_width = 600
    tex_fonts = {
        # Use LaTeX to write all text
        # "text.usetex": True,
        "font.family": "serif",
        # Use 10pt font in plots, to match 10pt font in document
        "axes.labelsize": 14,
        "font.size": 14,
        # Make the legend/label fonts a little smaller
        "legend.fontsize": 12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12
    }
    plt.rcParams.update(tex_fonts)

    ems_hits = np.sum([1 if vt < fcn else 0 for vt, fcn in zip(res['VanillaTransformer']['times'], res['FCN']['times'])])
    ems_performance = (ems_hits * 100) / len(res['VanillaTransformer']['times'])
    ems_textstr = ''.join(f'Runtime is lower for {ems_performance:.2f}% of the episodes with Transformer')

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)

    fig, axes = plt.subplots(1, 1, figsize=set_size(fig_width))
    fig.tight_layout()
    axes.title.set_text('Runtimes for each model')
    runtimes = []
    for model_name in res.keys():
        if model_name in models_to_use:
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


def plot_simulation_makespans(res: dict, models: list, reactive_mks: list = [], plot_reactive: bool =False, save_plots: bool = True):
    # Setup
    # plt.style.use('seaborn')
    # From Latex \textwidth
    fig_width = 600
    tex_fonts = {
        # Use LaTeX to write all text
        # "text.usetex": True,
        "font.family": "serif",
        # Use 10pt font in plots, to match 10pt font in document
        "axes.labelsize": 14,
        "font.size": 14,
        # Make the legend/label fonts a little smaller
        "legend.fontsize": 12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12
    }
    plt.rcParams.update(tex_fonts)

    # textstr_dict = dict.fromkeys(models, None)
    means_textstr_dict = dict.fromkeys(models, None)
    if plot_reactive and reactive_mks != []:
        means_textstr_dict = {**{'Reactive': ''.join(f'Reactive: {np.mean(reactive_mks):.2f} \u00B1 {np.std(reactive_mks):.2f}')}, **means_textstr_dict}
    for model_name in models:
        # if model_name != 'FCN':
        #     hits = np.sum([1 if vt < fcn else 0 for vt, fcn in zip(res[model_name]['makespan_sim_hist'], res['FCN']['makespan_sim_hist'])])
        #     performance = (hits * 100) / len(res[model_name]['makespan_sim_hist'])
            # if model_name == 'VanillaTransformer':
            #     textstr_dict[model_name] = ''.join(f'Makespan is lower for {performance:.2f}% of the trials\nwith Transformer')
            # else:
            #     textstr_dict[model_name] = ''.join(f'Makespan is lower for {performance:.2f}% of the trials\nwith {model_name}')
        if model_name == 'VanillaTransformer':
            means_textstr_dict[model_name] = ''.join(f'Transformer: {res[model_name]["makespan_sim_avg"]:.2f} \u00B1 {res[model_name]["makespan_sim_std"]:.2f}')
        else:
            means_textstr_dict[model_name] = ''.join(f'{model_name}: {res[model_name]["makespan_sim_avg"]:.2f} \u00B1 {res[model_name]["makespan_sim_std"]:.2f}')

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)

    fig, axes = plt.subplots(1, 1, figsize=set_size(fig_width))
    # plt.tight_layout()
    axes.title.set_text(f'Simulated makespans for each model (N = {len(res[list(res.keys())[0]]["makespan_sim_hist"])})')
    runtimes = []
    if plot_reactive and reactive_mks != []:
        runtimes.append(reactive_mks)
    for model_name in models:
        runtimes.append(res[model_name]['makespan_sim_hist'])

    if 'VanillaTransformer' in models:
        models = [m for m in models if m != 'VanillaTransformer']
    models.append('Transformer')
    if plot_reactive and reactive_mks != []:
        models.insert(0, 'Reactive')
    axes.hist(runtimes, alpha=0.5, label=models, bins=10)
    axes.legend()
    axes.set_xlabel('Episode Makespan [s]')
    axes.set_ylabel('Count [Episode]')


    x = 0.15
    y = 0.9
    # for model_name, textstr in textstr_dict.items():
    #     if textstr is not None:
    #         axes.text(x, y, textstr, transform=axes.transAxes, bbox=props, fontsize=20)
    #         y -= 0.11

    for model_name, textstr in means_textstr_dict.items():
        if textstr is not None:
            axes.text(x, y, textstr, transform=axes.transAxes, bbox=props, fontsize=20)
            y -= 0.11

    if save_plots:
        plt.savefig('../saved_data/imgs/makespan_prediction/makespan_simulation_histogram.png')
        plt.clf()
    else:
        plt.plot()

