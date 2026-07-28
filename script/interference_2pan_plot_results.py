#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import scipy.stats as stats

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_DIR = os.path.join(SCRIPT_DIR, "..", "plots") 
CSV_FILE = os.path.join(STATS_DIR, "simulation_results.csv")
PLOT_OUTPUT_DIR = os.path.join(STATS_DIR, "graphs")

NUM_DEVICE = 10
FONT_SIZE = 45

# 周波数から帯域幅へのマッピング
CH_TO_BW = {0: 50, 1: 100, 2: 200, 3: 50, 4: 100, 5: 200}
GROUP_A = [0, 1, 2]
GROUP_B = [3, 4, 5]

def parse_pos_file(filepath):
    """ .posファイルを解析し、ノードの初期座標（メートル単位）を抽出する """
    positions = {}
    if not os.path.exists(filepath):
        return positions
        
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) > 4 and parts[1] == "0":
                try:
                    positions[int(parts[0])] = (float(parts[2]), float(parts[3]))
                except ValueError:
                    continue
    return positions

def load_and_merge_data(csv_file, pos_dir):
    """ CSVとposファイルを結合し、デバイス単位の扱いやすいDataFrameに変換する """
    df_csv = pd.read_csv(csv_file)
    
    pan1_devs = list(range(3, 3 + NUM_DEVICE))
    pan2_devs = list(range(3 + NUM_DEVICE, 3 + 2 * NUM_DEVICE))
    
    device_data_list = []
    
    for _, row in df_csv.iterrows():
        pan1_ch = int(row['PAN1_CH'])
        pan2_ch = int(row['PAN2_CH'])
        dist_scenario = int(row['Distance'])
        
        # Offloadを整数(int)として取得するように修正
        pan1_offload = int(row['PAN1_Offload'])
        pan2_offload = int(row['PAN2_Offload'])
        seed = int(row['Seed'])
        
        # --- 帯域幅の取得とフォルダ名の生成（例: "50vs100"） ---
        bw1 = CH_TO_BW.get(pan1_ch, 0)
        bw2 = CH_TO_BW.get(pan2_ch, 0)
        bw_pair = f"{min(bw1, bw2)}vs{max(bw1, bw2)}"
        
        # --- 干渉あり/なしの判定ロジックを修正 ---
        # 同じグループに属していれば干渉あり、違えば干渉なし
        is_groupA_1 = pan1_ch in GROUP_A
        is_groupA_2 = pan2_ch in GROUP_A
        interf_type = "interf" if is_groupA_1 == is_groupA_2 else "no_interf"
            
        # POSファイルのパス（環境のファイル名に合わせて適宜調整してください）
        pos_filename = f"coord_dist_{dist_scenario}m_off_load_pan1_{pan1_offload}_pan2_{pan2_offload}_seed{seed}.pos"
        pos_path = os.path.join(pos_dir, pos_filename)
        if not os.path.exists(pos_path):
            pos_filename = f"{interf_type}_coord_dist_{dist_scenario}m_off_load_pan1_{pan1_offload}_pan2_{pan2_offload}_seed{seed}.pos"
            pos_path = os.path.join(pos_dir, pos_filename)

        positions = parse_pos_file(pos_path)
        if not positions:
            continue
            
        # --- PAN1のデータ抽出 ---
        for dev in pan1_devs:
            if 1 in positions and dev in positions:
                dist = np.sqrt((positions[dev][0] - positions[1][0])**2 + (positions[dev][1] - positions[1][1])**2)
            else:
                dist = np.nan
                
            ul_per = row.get(f'PAN1_Dev{dev}_UL_PER', 0.0)
            dl_per = row.get(f'PAN1_Dev{dev}_DL_PER', 0.0)
            rssi = row.get(f'PAN1_PC_RSSI_Avg_from_Dev{dev}', 0.0)
            
            device_data_list.append({
                'BW_Pair': bw_pair, 'Interf_Type': interf_type, 'Distance': dist_scenario,
                'PAN': 1, 'PAN1_Offload': pan1_offload, 'PAN2_Offload': pan2_offload,
                'Seed': seed, 'Dev_ID': dev, 'Dev_Dist': dist, 
                'UL_PER': ul_per, 'DL_PER': dl_per, 'Delta_PER': dl_per - ul_per, 'RSSI': rssi
            })
            
        # --- PAN2のデータ抽出 ---
        for dev in pan2_devs:
            if 2 in positions and dev in positions:
                dist = np.sqrt((positions[dev][0] - positions[2][0])**2 + (positions[dev][1] - positions[2][1])**2)
            else:
                dist = np.nan
                
            ul_per = row.get(f'PAN2_Dev{dev}_UL_PER', 0.0)
            dl_per = row.get(f'PAN2_Dev{dev}_DL_PER', 0.0)
            rssi = row.get(f'PAN2_PC_RSSI_Avg_from_Dev{dev}', 0.0)
            
            device_data_list.append({
                'BW_Pair': bw_pair, 'Interf_Type': interf_type, 'Distance': dist_scenario,
                'PAN': 2, 'PAN1_Offload': pan1_offload, 'PAN2_Offload': pan2_offload,
                'Seed': seed, 'Dev_ID': dev, 'Dev_Dist': dist, 
                'UL_PER': ul_per, 'DL_PER': dl_per, 'Delta_PER': dl_per - ul_per, 'RSSI': rssi
            })

    return pd.DataFrame(device_data_list).dropna()


# ==========================================
# グラフ描画関数
# ==========================================

def add_errorbar_plot(df, per_col, color, label, ax):
    bin_size = 100
    if df.empty: return
    
    bins = np.arange(50, df['Dev_Dist'].max() + bin_size, bin_size)
    df = df.copy()
    df['bin'] = pd.cut(df['Dev_Dist'], bins=bins, labels=bins[:-1] + bin_size/2)
    stats_df = df.groupby('bin', observed=False)[per_col].agg(['mean', 'count', 'std']).dropna()
    
    ci95_hi = []
    for i in range(len(stats_df)):
        m, n, s = stats_df.iloc[i][['mean', 'count', 'std']]
        if n > 1:
            interval = stats.t.ppf(0.975, n-1) * (s / np.sqrt(n))
            ci95_hi.append(interval)
        else:
            ci95_hi.append(0)

    ax.errorbar(stats_df.index.astype(float), stats_df['mean'], yerr=ci95_hi, fmt='o', color=color, label=label,
                capsize=8, capthick=3, elinewidth=3, markersize=12)

def plot_distance_vs_per_errorbar(df_pan, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))
    add_errorbar_plot(df_pan, 'UL_PER', 'blue', 'UpLink', ax)
    add_errorbar_plot(df_pan, 'DL_PER', 'red', 'DownLink', ax)

    ax.set_ylim(0.0, 1.0)
    ax.tick_params(axis="both", labelsize=FONT_SIZE, width=3.0, which="major", length=20)
    leg = ax.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.tight_layout()
    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()

def interf_diff_errorbar(df_interf, df_no_interf, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))
    add_errorbar_plot(df_interf, 'Delta_PER', 'red', 'With Interference', ax)
    add_errorbar_plot(df_no_interf, 'Delta_PER', 'blue', 'Without Interference', ax)

    ax.set_ylim(-1.0, 0.5)
    ax.tick_params(axis="both", labelsize=FONT_SIZE, width=3.0, which="major", length=20)
    leg = ax.legend(fontsize=FONT_SIZE - 10)
    leg.get_frame().set_linewidth(1.8)
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.tight_layout()
    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()

def plot_delta_per_analysis(df, filename, plot_dir):
    df_valid = df[df['RSSI'] != 0.0]
    bins = np.arange(-50, -111, -10)
    bin_data_list, labels = [], []
    
    for i in range(len(bins) - 1):
        upper, lower = bins[i], bins[i+1]
        in_bin_mask = (df_valid['RSSI'] > lower) & (df_valid['RSSI'] <= upper)
        bin_data = df_valid[in_bin_mask]['Delta_PER'].values
        labels.append(f"[{upper}, {lower})")
        bin_data_list.append(bin_data if len(bin_data) > 0 else [])

    fig, ax = plt.subplots(figsize=(10, 10))
    plot_indices = [i for i, d in enumerate(bin_data_list) if len(d) > 0]
    ax.tick_params(axis="both", labelsize=FONT_SIZE-20, width=3.0, which="major", length=20)

    if plot_indices:
        ax.boxplot([bin_data_list[i] for i in plot_indices], labels=[labels[i] for i in plot_indices])
    
    ax.set_ylim(-1.0, 1.0)
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    
    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()

def plot_variance_distribution_boxplot(df, filename, plot_dir):
    bins = np.arange(0, -121, -10)
    variances_per_bin = [[] for _ in range(len(bins) - 1)]
    bin_labels = [f"[{bins[i]}, {bins[i+1]})" for i in range(len(bins) - 1)]
    
    for seed, group in df[df['RSSI'] != 0.0].groupby('Seed'):
        for b in range(len(bins) - 1):
            upper, lower = bins[b], bins[b+1]
            mask = (group['RSSI'] > lower) & (group['RSSI'] <= upper)
            bin_values = group[mask]['Delta_PER'].values
            if len(bin_values) > 1:
                variances_per_bin[b].append(np.var(bin_values))

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.tick_params(axis="both", labelsize=FONT_SIZE-20, width=3.0, which="major", length=20)
    
    plot_data = [d for d in variances_per_bin if len(d) > 0]
    plot_labels = [l for d, l in zip(variances_per_bin, bin_labels) if len(d) > 0]

    if plot_data:
        ax.boxplot(plot_data, labels=plot_labels)
    
    ax.set_ylim(0, 0.4)
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)
    
    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()


# ==========================================
# メイン実行処理
# ==========================================
def main():
    print("--- Loading and Merging Data from CSV and POS files ---")
    df_all = load_and_merge_data(CSV_FILE, STATS_DIR)
    
    if df_all.empty:
        print("データが見つかりませんでした。CSVパスとPOSファイルの存在を確認してください。")
        sys.exit(1)

    # 1. 距離別・干渉別の箱ひげ図プロット
    # DataFrameを (帯域幅ペア, 距離, PAN1負荷, PAN2負荷, 干渉有無) でグループ化
    print("--- Generating Distance-specific Boxplots ---")
    group_cols_box = ['BW_Pair', 'Distance', 'PAN1_Offload', 'PAN2_Offload', 'Interf_Type']
    for (bw_pair, dist, p1_load, p2_load, interf_type), group_df in df_all.groupby(group_cols_box):
        
        # 保存先フォルダ: plots/50vs100/1500m/interf/
        plot_dir = os.path.join(PLOT_OUTPUT_DIR, bw_pair, f"{dist}m", interf_type)
        
        df_pan1 = group_df[group_df['PAN'] == 1]
        df_pan2 = group_df[group_df['PAN'] == 2]
        
        # Boxplot出力
        if not df_pan1.empty:
            plot_delta_per_analysis(df_pan1, f"pan1_box_pan1_{p1_load}_pan2_{p2_load}.pdf", plot_dir)
            plot_variance_distribution_boxplot(df_pan1, f"pan1_s_pan1_{p1_load}_pan2_{p2_load}.pdf", plot_dir)
        if not df_pan2.empty:
            plot_delta_per_analysis(df_pan2, f"pan2_box_pan1_{p1_load}_pan2_{p2_load}.pdf", plot_dir)
            plot_variance_distribution_boxplot(df_pan2, f"pan2_s_pan1_{p1_load}_pan2_{p2_load}.pdf", plot_dir)

    # 2. 距離を横軸としたエラーバーのプロット（距離フォルダに入れると点が1つになるため、帯域幅フォルダ直下に配置）
    print("--- Generating Distance-aggregated Errorbars ---")
    group_cols_err = ['BW_Pair', 'PAN1_Offload', 'PAN2_Offload']
    for (bw_pair, p1_load, p2_load), group_df in df_all.groupby(group_cols_err):
        
        # エラーバー用のフォルダ: plots/50vs100/errorbars/
        errorbar_dir = os.path.join(PLOT_OUTPUT_DIR, bw_pair, "errorbars")
        
        df_interf = group_df[group_df['Interf_Type'] == 'interf']
        df_no_interf = group_df[group_df['Interf_Type'] == 'no_interf']
        
        # 干渉あり/なし個別のエラーバー
        if not df_interf.empty:
            plot_distance_vs_per_errorbar(df_interf[df_interf['PAN']==1], f"pan1_errorbar_interf_{p1_load}_{p2_load}.pdf", errorbar_dir)
            plot_distance_vs_per_errorbar(df_interf[df_interf['PAN']==2], f"pan2_errorbar_interf_{p1_load}_{p2_load}.pdf", errorbar_dir)
        
        if not df_no_interf.empty:
            plot_distance_vs_per_errorbar(df_no_interf[df_no_interf['PAN']==1], f"pan1_errorbar_no_interf_{p1_load}_{p2_load}.pdf", errorbar_dir)
            plot_distance_vs_per_errorbar(df_no_interf[df_no_interf['PAN']==2], f"pan2_errorbar_no_interf_{p1_load}_{p2_load}.pdf", errorbar_dir)
            
        # 干渉あり/なしの比較エラーバー
        if not df_interf.empty and not df_no_interf.empty:
            interf_diff_errorbar(
                df_interf[df_interf['PAN']==1], 
                df_no_interf[df_no_interf['PAN']==1], 
                f"PAN1_diff_errorbar_p1_{p1_load}_p2_{p2_load}.pdf", 
                errorbar_dir
            )

    print("All plots generated successfully!")

if __name__ == "__main__":
    main()