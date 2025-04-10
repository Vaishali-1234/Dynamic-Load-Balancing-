import psutil
import time
import threading
import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from matplotlib.figure import Figure
import matplotlib.colors as mcolors
import subprocess
import os
import platform

L_HIGH = 80
L_LOW = 30
monitoring = False
cpu_history = []
balanced_processes = {}  # Keep track of processes we've already balanced

# Modern color palette
DARK_BG = "#1e1e2e"         # Dark background
PANEL_BG = "#313244"         # Panel background
ACCENT = "#cba6f7"           # Primary accent
ACCENT_ALT = "#89b4fa"       # Secondary accent
TEXT_COLOR = "#f5f5f9"       # Light text
HIGHLIGHT = "#f38ba8"        # Highlight/warning
SUCCESS = "#a6e3a1"          # Success indicator
NEUTRAL = "#89dceb"          # Neutral indicator
BORDER_COLOR = "#6c7086"     # Border color

def get_cpu_load():
    return psutil.cpu_percent(percpu=True)

def predict_overload():
    global cpu_history
    if len(cpu_history) < 5:
        return None
    avg_usage = np.mean(cpu_history[-5:], axis=0)
    for i, usage in enumerate(avg_usage):
        if usage > L_HIGH - 10:
            return i
    return None

def get_core_processes(core_num):
    """Get processes running on a specific CPU core"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            # On some systems, cpu_num might not be available or accurate
            # So we use cpu_percent to estimate load contribution
            if proc.info['cpu_percent'] > 1.0:  # Filter out idle processes
                processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    # Sort by CPU usage (highest first)
    processes.sort(key=lambda p: p.info['cpu_percent'], reverse=True)
    return processes

def set_process_affinity(pid, cpu_list):
    """Set CPU affinity for a process"""
    try:
        process = psutil.Process(pid)
        current_affinity = process.cpu_affinity()
        
        # Don't change if it's already set correctly or if it's a system process with special affinity
        if set(cpu_list) == set(current_affinity) or len(current_affinity) > len(psutil.cpu_count()):
            return False
            
        process.cpu_affinity(cpu_list)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    except Exception as e:
        log_action(f"Error setting affinity: {str(e)}")
        return False

def can_balance_process(proc):
    """Check if we can and should balance this process"""
    try:
        # Skip system processes
        if proc.pid < 100:
            return False
            
        # Skip processes that were recently balanced
        if proc.pid in balanced_processes and time.time() - balanced_processes[proc.pid] < 30:
            return False
            
        # Skip certain critical system processes
        if proc.name().lower() in ['system', 'systemd', 'kernel', 'wininit', 'services.exe', 'explorer.exe']:
            return False
            
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

def perform_load_balancing(overloaded_core, underloaded_core):
    """Perform actual load balancing by moving processes between cores, considering priority."""
    try:
        # Get processes from the overloaded core
        processes = get_core_processes(overloaded_core)
        
        # Sort processes by their niceness value (higher niceness = lower priority)
        def get_niceness(proc):
            try:
                return proc.nice()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                return 999  # Assign a very high niceness to inaccessible processes
        
        processes.sort(key=get_niceness)
        
        for proc in processes:
            if can_balance_process(proc):
                try:
                    priority = proc.nice()
                    current_name = proc.name()
                    current_pid = proc.pid
                    
                    # Basic priority consideration: Don't move very high-priority processes lightly
                    if priority <= -10 and get_cpu_load()[overloaded_core] <= L_HIGH + 5:
                        log_action(f"⚠️ Not moving high-priority process {current_name} (PID: {current_pid})")
                        continue
                        
                    if set_process_affinity(current_pid, [underloaded_core]):
                        balanced_processes[current_pid] = time.time()  # Mark as recently balanced
                        log_action(f"🔄 Moved process {current_name} (PID: {current_pid}, Nice: {priority}) from CPU {overloaded_core} to CPU {underloaded_core}")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                    log_action(f"Error accessing process {proc.pid}: {e}")
                    continue
                except Exception as e:
                    log_action(f"Error handling process {proc.pid}: {e}")
                    continue
        
        return False
    except Exception as e:
        log_action(f"Error during balancing: {str(e)}")
        return False

def balance_load(cpu_loads):
    max_idx = predict_overload()
    if max_idx is None:
        max_idx = cpu_loads.index(max(cpu_loads))
    min_idx = cpu_loads.index(min(cpu_loads))
    
    if cpu_loads[max_idx] > L_HIGH and cpu_loads[min_idx] < L_LOW:
        log_action(f"⚖️ Detected imbalance: CPU {max_idx} ({cpu_loads[max_idx]:.1f}%) ➡ CPU {min_idx} ({cpu_loads[min_idx]:.1f}%)")
        
        # Perform actual load balancing
        if perform_load_balancing(max_idx, min_idx):
            return max_idx, min_idx
    
    return None, None

def log_action(message):
    timestamp = time.strftime("%H:%M:%S")
    log_text.insert(tk.END, f"[{timestamp}] {message}\n")
    log_text.see(tk.END)

def create_gradient_colors(cpu_loads):
    colors = []
    for load in cpu_loads:
        if load > L_HIGH:
            colors.append(HIGHLIGHT)
        elif load < L_LOW:
            colors.append(NEUTRAL)
        else:
            # Create gradient between low and high
            ratio = (load - L_LOW) / (L_HIGH - L_LOW)
            r1, g1, b1 = mcolors.to_rgb(NEUTRAL)
            r2, g2, b2 = mcolors.to_rgb(SUCCESS)
            r = r1 + (r2 - r1) * ratio
            g = g1 + (g2 - g1) * ratio
            b = b1 + (b2 - b1) * ratio
            colors.append(mcolors.to_hex((r, g, b)))
    return colors

def update_cpu_graph():
    global monitoring, cpu_history
    if not monitoring:
        return
        
    cpu_loads = get_cpu_load()
    cpu_history.append(cpu_loads)
    if len(cpu_history) > 20:  # Increased history for smoother trends
        cpu_history.pop(0)

    max_idx, min_idx = balance_load(cpu_loads)
    
    # Clear the figure for redrawing
    ax.clear()
    ax.set_facecolor(PANEL_BG)
    fig.patch.set_facecolor(DARK_BG)
    
    # Create gradient colors for bars
    colors = create_gradient_colors(cpu_loads)
    
    # Plot the bar chart with rounded corners
    bars = ax.bar(
        range(len(cpu_loads)), 
        cpu_loads, 
        color=colors, 
        edgecolor=BORDER_COLOR, 
        linewidth=1, 
        width=0.65,
        alpha=0.9
    )
    
    # Add horizontal lines for thresholds
    ax.axhline(y=L_HIGH, color=HIGHLIGHT, alpha=0.3, linestyle='--', linewidth=1)
    ax.axhline(y=L_LOW, color=NEUTRAL, alpha=0.3, linestyle='--', linewidth=1)
    
    # Add text labels for high/low thresholds
    ax.text(-0.5, L_HIGH + 2, f"High ({L_HIGH}%)", color=HIGHLIGHT, alpha=0.7, fontsize=8)
    ax.text(-0.5, L_LOW - 4, f"Low ({L_LOW}%)", color=NEUTRAL, alpha=0.7, fontsize=8)
    
    # Add percentage text on top of each bar
    for i, bar in enumerate(bars):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 2,
            f"{int(height)}%",
            ha='center',
            color=TEXT_COLOR,
            fontsize=9
        )
    
    # Add load balancing indicators if needed
    if max_idx is not None and min_idx is not None:
        ax.text(max_idx, cpu_loads[max_idx] + 8, "⬇️", ha='center', fontsize=16)
        ax.text(min_idx, cpu_loads[min_idx] + 8, "⬆️", ha='center', fontsize=16)
    
    # Customize the graph appearance
    ax.set_ylim(0, 100)
    ax.set_ylabel("CPU Usage (%)", fontsize=10, color=TEXT_COLOR)
    ax.set_xticks(range(len(cpu_loads)))
    ax.set_xticklabels([f"CPU {i}" for i in range(len(cpu_loads))], fontsize=9, color=TEXT_COLOR)
    
    # Style the axes
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(BORDER_COLOR)
    ax.spines['left'].set_color(BORDER_COLOR)
    ax.tick_params(axis='both', colors=TEXT_COLOR)
    
    # Add line graph of historical data if we have enough history
    if len(cpu_history) > 1:
        # Create a small inset axes for the history graph
        if not hasattr(update_cpu_graph, 'history_ax'):
            update_cpu_graph.history_ax = ax.inset_axes([0.65, 0.05, 0.3, 0.2])
        
        history_ax = update_cpu_graph.history_ax
        history_ax.clear()
        history_ax.set_facecolor(PANEL_BG)
        
        # Plot small lines for each CPU
        for i in range(len(cpu_loads)):
            values = [history[i] for history in cpu_history]
            history_ax.plot(values, alpha=0.7, linewidth=1, color=colors[i])
        
        history_ax.set_title("History", fontsize=8, color=TEXT_COLOR)
        history_ax.tick_params(axis='both', colors=TEXT_COLOR, labelsize=6)
        history_ax.set_ylim(0, 100)
        history_ax.grid(alpha=0.1)
        
    # Update the canvas
    canvas.draw()
    
    # Set up the next update
    root.after(1000, update_cpu_graph)

def update_process_list():
    """Update the list of top CPU using processes"""
    if not monitoring:
        return
        
    # Clear current list
    process_list.delete(0, tk.END)
    
    # Get top CPU using processes
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    # Sort by CPU usage
    processes.sort(key=lambda p: p.info['cpu_percent'], reverse=True)
    
    # Take top 10
    top_processes = processes[:10]
    
    # Add to list
    for i, proc in enumerate(top_processes):
        try:
            cpu_percent = proc.info['cpu_percent']
            if cpu_percent > 0.1:  # Only show active processes
                try:
                    # Try to get process affinity
                    try:
                        affinity = proc.cpu_affinity()
                        affinity_str = f"CPUs: {','.join(map(str, affinity))}" if len(affinity) < 5 else f"CPUs: {len(affinity)}"
                    except:
                        affinity_str = "N/A"
                    
                    # Try to get process priority (niceness)
                    try:
                        priority = proc.nice()
                        priority_str = f"Nice: {priority}"
                    except:
                        priority_str = ""
                        
                    list_item = f"{proc.info['name']} (PID: {proc.info['pid']}) - {cpu_percent:.1f}% - {affinity_str} {priority_str}"
                    process_list.insert(tk.END, list_item)
                    
                    # Color-code based on CPU usage
                    if cpu_percent > 50:
                        process_list.itemconfig(i, {'fg': HIGHLIGHT})
                    elif cpu_percent > 20:
                        process_list.itemconfig(i, {'fg': ACCENT})
                except:
                    pass
        except:
            pass
    
    # Schedule next update
    root.after(2000, update_process_list)

def check_admin_rights():
    """Check if application is running with admin rights"""
    try:
        if platform.system() == "Windows":
            # Windows admin check
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            # Linux/Mac admin check
            return os.geteuid() == 0
    except:
        return False

def check_and_notify_about_rights():
    """Check admin rights and notify user if needed"""
    has_admin = check_admin_rights()
    if not has_admin:
        log_action("⚠️ WARNING: Not running with administrator privileges.")
        log_action("    Some load balancing features may be limited.")
        log_action("    Restart application as administrator for full functionality.")
        return False
    else:
        log_action("✅ Running with administrator privileges. Full functionality available.")
        return True

def start_monitoring():
    global monitoring
    if not monitoring:
        monitoring = True
        log_action("▶️ Monitoring Started")
        status_label.config(text="Status: Active", fg=SUCCESS)
        start_button.config(state=tk.DISABLED)
        stop_button.config(state=tk.NORMAL)
        update_cpu_graph()
        update_process_list()
        
        # Check admin rights
        check_and_notify_about_rights()

def stop_monitoring():
    global monitoring
    if monitoring:
        monitoring = False
        log_action("⏹️ Monitoring Stopped")
        status_label.config(text="Status: Inactive", fg=HIGHLIGHT)
        start_button.config(state=tk.NORMAL)
        stop_button.config(state=tk.DISABLED)

def clear_log():
    log_text.delete(1.0, tk.END)

def show_dashboard():
    home_frame.pack_forget()
    creators_frame.pack_forget()
    dashboard_frame.pack(fill="both", expand=True)
    update_active_nav_button("dashboard")

def show_home():
    dashboard_frame.pack_forget()
    creators_frame.pack_forget()
    home_frame.pack(fill="both", expand=True)
    update_active_nav_button("home")

def show_creators():
    dashboard_frame.pack_forget()
    home_frame.pack_forget()
    creators_frame.pack(fill="both", expand=True)
    update_active_nav_button("creators")

def update_active_nav_button(active):
    for name, button in nav_buttons_dict.items():
        if name == active:
            button.config(bg=ACCENT, fg=DARK_BG)
        else:
            button.config(bg=PANEL_BG, fg=TEXT_COLOR)

def create_hover_effect(button):
    def on_enter(e):
        if button['bg'] != ACCENT:  # Only change if not the active button
            button['bg'] = BORDER_COLOR
    
    def on_leave(e):
        if button['bg'] != ACCENT:  # Only change if not the active button
            button['bg'] = PANEL_BG
    
    button.bind("<Enter>", on_enter)
    button.bind("<Leave>", on_leave)

# Set up the main window
root = tk.Tk()
root.title("⚡ CPU Load Balancer Pro 🔥")
root.geometry("1200x800")
root.configure(bg=DARK_BG)

# Create custom font styles
title_font = ("Segoe UI", 36, "bold")
subtitle_font = ("Segoe UI", 18)
body_font = ("Segoe UI", 14)
button_font = ("Segoe UI", 12, "bold")
small_font = ("Segoe UI", 10)

# Home Page
home_frame = tk.Frame(root, bg=DARK_BG)

# Navigation Bar (shared across all frames)
nav_frame = tk.Frame(root, bg=PANEL_BG, height=60)
nav_frame.pack(fill="x", side="top")

nav_logo = tk.Label(nav_frame, text="⚡ CPU BALANCER", font=("Segoe UI", 14, "bold"), bg=PANEL_BG, fg=ACCENT)
nav_logo.pack(side="left", padx=20, pady=10)

nav_buttons_frame = tk.Frame(nav_frame, bg=PANEL_BG)
nav_buttons_frame.pack(side="right", padx=20, pady=10)

nav_buttons_dict = {}
for text, command, name in [
    ("Home", show_home, "home"),
    ("Dashboard", show_dashboard, "dashboard"),
    ("Creators", show_creators, "creators")
]:
    btn = tk.Button(
        nav_buttons_frame, 
        text=text, 
        command=command, 
        font=button_font, 
        bg=PANEL_BG, 
        fg=TEXT_COLOR, 
        relief="flat", 
        padx=15, 
        pady=5,
        borderwidth=0,
        activebackground=ACCENT_ALT,
        activeforeground=DARK_BG
    )
    btn.pack(side="left", padx=5)
    nav_buttons_dict[name] = btn
    create_hover_effect(btn)

# Home Page Content
home_content = tk.Frame(home_frame, bg=DARK_BG)
home_content.pack(fill="both", expand=True, padx=40, pady=30)

# Welcome Title with gradient effect using Canvas
title_canvas = tk.Canvas(home_content, bg=DARK_BG, height=80, width=700, highlightthickness=0)
title_canvas.pack(pady=(40, 0))

title_canvas.create_text(350, 40, text="CPU Load Balancer Pro", font=title_font, fill=ACCENT)

# Subtitle with animation effect
subtitle_label = tk.Label(home_content, text="Optimize Your System's Performance", fg=TEXT_COLOR, bg=DARK_BG, font=subtitle_font)
subtitle_label.pack(pady=(10, 40))

# Card-style info boxes
info_container = tk.Frame(home_content, bg=DARK_BG)
info_container.pack(fill="both", expand=True, pady=20)
info_container.grid_columnconfigure(0, weight=1)
info_container.grid_columnconfigure(1, weight=1)

# Left info card
left_card = tk.Frame(info_container, bg=PANEL_BG, padx=25, pady=25, borderwidth=0)
left_card.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

left_title = tk.Label(left_card, text="Real-time Monitoring", font=("Segoe UI", 16, "bold"), fg=ACCENT, bg=PANEL_BG)
left_title.pack(anchor="w", pady=(0, 15))

left_features = [
    "🔹 Live CPU core activity tracking",
    "🔹 Advanced multi-core visualization",
    "🔹 Intelligent overload prediction",
    "🔹 Customizable threshold alerts"
]

for feature in left_features:
    feature_label = tk.Label(left_card, text=feature, font=body_font, fg=TEXT_COLOR, bg=PANEL_BG, anchor="w", justify="left")
    feature_label.pack(fill="x", pady=5, anchor="w")

# Right info card
right_card = tk.Frame(info_container, bg=PANEL_BG, padx=25, pady=25, borderwidth=0)
right_card.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

right_title = tk.Label(right_card, text="Smart Load Balancing", font=("Segoe UI", 16, "bold"), fg=ACCENT, bg=PANEL_BG)
right_title.pack(anchor="w", pady=(0, 15))

right_features = [
    "🔹 Priority-aware task distribution",
    "🔹 Heat reduction strategies",
    "🔹 Performance optimization",
    "🔹 Detailed activity logging"
]

for feature in right_features:
    feature_label = tk.Label(right_card, text=feature, font=body_font, fg=TEXT_COLOR, bg=PANEL_BG, anchor="w", justify="left")
    feature_label.pack(fill="x", pady=5, anchor="w")

# Main action button
action_frame = tk.Frame(home_content, bg=DARK_BG, pady=30)
action_frame.pack(fill="x")

proceed_button = tk.Button(
    action_frame,
    text="Enter Dashboard",
    command=show_dashboard,
    font=("Segoe UI", 16, "bold"),
    fg=DARK_BG,
    bg=ACCENT,
    width=20,
    height=2,
    relief="flat",
    borderwidth=0
)
proceed_button.pack()

# Creators Page
creators_frame = tk.Frame(root, bg=DARK_BG)

creators_content = tk.Frame(creators_frame, bg=DARK_BG)
creators_content.pack(fill="both", expand=True, padx=40, pady=40)

creators_title = tk.Label(creators_content, text="Meet the Team", fg=ACCENT, bg=DARK_BG, font=("Segoe UI", 28, "bold"))
creators_title.pack(pady=(20, 40))

# Creator cards in a grid
creators_grid = tk.Frame(creators_content, bg=DARK_BG)
creators_grid.pack(fill="both", expand=True)

creators_data = [
    {
        "name": "Amal Krishna",
        "role": "Lead UI/UX Designer",
        "desc": "Created the dashboard interface and real-time monitoring visualizations.",
        "emoji": "🎨"
    },
    {
        "name": "Jens Mathew Thomas",
        "role": "Algorithm Developer",
        "desc": "Implemented the predictive load balancing system and navigation logic.",
        "emoji": "⚙️"
    },
    {
        "name": "Vaishali V",
        "role": "Content & UX Specialist",
        "desc": "Designed the user experience workflow and created documentation.",
        "emoji": "📝"
    }
]

for i, creator in enumerate(creators_data):
    card = tk.Frame(creators_grid, bg=PANEL_BG, padx=20, pady=20)
    card.grid(row=i//2, column=i%2, padx=15, pady=15, sticky="nsew")
    
    # Creator emoji icon
    emoji = tk.Label(card, text=creator["emoji"], font=("Segoe UI", 36), bg=PANEL_BG, fg=TEXT_COLOR)
    emoji.pack(pady=(0, 10))
    
    # Creator name
    name = tk.Label(card, text=creator["name"], font=("Segoe UI", 16, "bold"), bg=PANEL_BG, fg=ACCENT)
    name.pack(pady=(0, 5))
    
    # Creator role
    role = tk.Label(card, text=creator["role"], font=("Segoe UI", 12, "italic"), bg=PANEL_BG, fg=ACCENT_ALT)
    role.pack(pady=(0, 10))
    
    # Creator description
    desc = tk.Label(card, text=creator["desc"], font=("Segoe UI", 10), bg=PANEL_BG, fg=TEXT_COLOR, wraplength=250)
    desc.pack()

# Team note
team_note = tk.Label(
    creators_content, 
    text="Together, we developed the Priority-Aware Dynamic Load Balancing algorithm to optimize multi-core performance.", 
    font=("Segoe UI", 12), 
    fg=TEXT_COLOR, 
    bg=DARK_BG
)
team_note.pack(pady=30)

# Dashboard UI
dashboard_frame = tk.Frame(root, bg=DARK_BG)

# Split dashboard into a top and bottom section
dashboard_top = tk.Frame(dashboard_frame, bg=DARK_BG)
dashboard_top.pack(fill="x", expand=False, padx=20, pady=10)

# Status bar and controls
status_bar = tk.Frame(dashboard_top, bg=PANEL_BG, padx=15, pady=10)
status_bar.pack(fill="x", pady=10)

status_label = tk.Label(
    status_bar, 
    text="Status: Inactive", 
    font=("Segoe UI", 10, "bold"), 
    bg=PANEL_BG, 
    fg=HIGHLIGHT, 
    padx=15, 
    pady=5
)
status_label.pack(side="left")

system_info = f"System: {psutil.cpu_count()} CPUs | {psutil.virtual_memory().total // (1024**3)}GB RAM"
system_label = tk.Label(
    status_bar, 
    text=system_info, 
    font=("Segoe UI", 10), 
    bg=PANEL_BG, 
    fg=TEXT_COLOR, 
    padx=15, 
    pady=5
)
system_label.pack(side="right")

# Control buttons in their own panel
control_panel = tk.Frame(dashboard_top, bg=PANEL_BG, padx=15, pady=15)
control_panel.pack(fill="x", pady=10)

control_label = tk.Label(
    control_panel, 
    text="Controls", 
    font=("Segoe UI", 12, "bold"), 
    bg=PANEL_BG, 
    fg=ACCENT, 
    padx=10, 
    pady=5
)
control_label.pack(side="left")

button_container = tk.Frame(control_panel, bg=PANEL_BG)
button_container.pack(side="right")

# Start button
start_button = tk.Button(
    button_container,
    text="▶️ Start",
    command=start_monitoring,
    font=("Segoe UI", 11, "bold"),
    bg=SUCCESS,
    fg=DARK_BG,
    width=8,
    relief="flat",
    padx=10,
    pady=5
)
start_button.pack(side="left", padx=5)

# Stop button
stop_button = tk.Button(
    button_container,
    text="⏹️ Stop",
    command=stop_monitoring,
    font=("Segoe UI", 11, "bold"),
    bg=HIGHLIGHT,
    fg=DARK_BG,
    width=8,
    relief="flat",
    padx=10,
    pady=5
)
stop_button.pack(side="left", padx=5)
stop_button.config(state=tk.DISABLED)

# Dashboard main content (3-column layout)
dashboard_main = tk.Frame(dashboard_frame, bg=DARK_BG)
dashboard_main.pack(fill="both", expand=True, padx=20, pady=10)
dashboard_main.columnconfigure(0, weight=6)  # Graph gets more space
dashboard_main.columnconfigure(1, weight=4)  # Log gets less space
dashboard_main.columnconfigure(2, weight=3)  # Process list
dashboard_main.rowconfigure(0, weight=1)     # All expand vertically

# Graph panel (left column)
graph_panel = tk.Frame(dashboard_main, bg=PANEL_BG, padx=15, pady=15)
graph_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

graph_title = tk.Label(
    graph_panel, 
    text="CPU Load Distribution", 
    font=("Segoe UI", 14, "bold"), 
    bg=PANEL_BG, 
    fg=ACCENT
)
graph_title.pack(pady=(0, 10))

# Create the figure and canvas
fig = Figure(figsize=(8, 4), dpi=100)
ax = fig.add_subplot(111)
fig.patch.set_facecolor(DARK_BG)
ax.set_facecolor(PANEL_BG)

canvas = FigureCanvasTkAgg(fig, master=graph_panel)
canvas.get_tk_widget().pack(fill="both", expand=True)

log_panel = tk.Frame(dashboard_main, bg=PANEL_BG, padx=15, pady=15)
log_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

log_header = tk.Frame(log_panel, bg=PANEL_BG)
log_header.pack(fill="x", pady=(0, 10))

log_title = tk.Label(
    log_header, 
    text="Activity Log", 
    font=("Segoe UI", 14, "bold"), 
    bg=PANEL_BG, 
    fg=ACCENT
)
log_title.pack(side="left")

clear_log_button = tk.Button(
    log_header,
    text="Clear",
    command=clear_log,
    font=("Segoe UI", 9),
    bg=BORDER_COLOR,
    fg=TEXT_COLOR,
    relief="flat",
    padx=8,
    pady=2
)
clear_log_button.pack(side="right")

# Log text area with scrollbar
log_frame = tk.Frame(log_panel, bg=DARK_BG)
log_frame.pack(fill="both", expand=True)

scrollbar = tk.Scrollbar(log_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

log_text = tk.Text(
    log_frame,
    height=15,
    bg=DARK_BG,
    fg=TEXT_COLOR,
    font=("Consolas", 10),
    padx=10,
    pady=10,
    yscrollcommand=scrollbar.set
)
log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scrollbar.config(command=log_text.yview)

# Process list panel (right column)
process_panel = tk.Frame(dashboard_main, bg=PANEL_BG, padx=15, pady=15)
process_panel.grid(row=0, column=2, sticky="nsew")

process_header = tk.Frame(process_panel, bg=PANEL_BG)
process_header.pack(fill="x", pady=(0, 10))

process_title = tk.Label(
    process_header, 
    text="Active Processes", 
    font=("Segoe UI", 14, "bold"), 
    bg=PANEL_BG, 
    fg=ACCENT
)
process_title.pack(side="left")

refresh_button = tk.Button(
    process_header,
    text="Refresh",
    command=lambda: update_process_list(),
    font=("Segoe UI", 9),
    bg=BORDER_COLOR,
    fg=TEXT_COLOR,
    relief="flat",
    padx=8,
    pady=2
)
refresh_button.pack(side="right")

# Process list with scrollbar
process_list_frame = tk.Frame(process_panel, bg=DARK_BG)
process_list_frame.pack(fill="both", expand=True)

process_scrollbar = tk.Scrollbar(process_list_frame)
process_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

process_list = tk.Listbox(
    process_list_frame,
    bg=DARK_BG,
    fg=TEXT_COLOR,
    font=("Consolas", 10),
    selectbackground=ACCENT,
    selectforeground=DARK_BG,
    yscrollcommand=process_scrollbar.set
)
process_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
process_scrollbar.config(command=process_list.yview)

# Advanced settings frame at the bottom of dashboard
settings_frame = tk.Frame(dashboard_frame, bg=PANEL_BG, padx=15, pady=15)
settings_frame.pack(fill="x", padx=20, pady=10)

settings_title = tk.Label(
    settings_frame, 
    text="Balance Settings", 
    font=("Segoe UI", 14, "bold"), 
    bg=PANEL_BG, 
    fg=ACCENT
)
settings_title.pack(anchor="w", pady=(0, 10))

# Settings controls in a grid
settings_grid = tk.Frame(settings_frame, bg=PANEL_BG)
settings_grid.pack(fill="x")

# High threshold setting
high_label = tk.Label(
    settings_grid,
    text="High Load Threshold:",
    font=small_font,
    bg=PANEL_BG,
    fg=TEXT_COLOR
)
high_label.grid(row=0, column=0, sticky="w", padx=10, pady=5)

high_slider = tk.Scale(
    settings_grid,
    from_=50,
    to=95,
    orient="horizontal",
    length=200,
    bg=PANEL_BG,
    fg=TEXT_COLOR,
    highlightthickness=0,
    troughcolor=BORDER_COLOR,
    activebackground=ACCENT
)
high_slider.set(L_HIGH)
high_slider.grid(row=0, column=1, padx=10, pady=5)

def update_high_threshold(val):
    global L_HIGH
    L_HIGH = int(val)
    log_action(f"⚙️ High load threshold set to {L_HIGH}%")

high_slider.config(command=update_high_threshold)

# Low threshold setting
low_label = tk.Label(
    settings_grid,
    text="Low Load Threshold:",
    font=small_font,
    bg=PANEL_BG,
    fg=TEXT_COLOR
)
low_label.grid(row=1, column=0, sticky="w", padx=10, pady=5)

low_slider = tk.Scale(
    settings_grid,
    from_=5,
    to=45,
    orient="horizontal",
    length=200,
    bg=PANEL_BG,
    fg=TEXT_COLOR,
    highlightthickness=0,
    troughcolor=BORDER_COLOR,
    activebackground=ACCENT
)
low_slider.set(L_LOW)
low_slider.grid(row=1, column=1, padx=10, pady=5)

def update_low_threshold(val):
    global L_LOW
    L_LOW = int(val)
    log_action(f"⚙️ Low load threshold set to {L_LOW}%")

low_slider.config(command=update_low_threshold)

# Right panel in settings grid - balancing options
balance_options_frame = tk.Frame(settings_grid, bg=PANEL_BG)
balance_options_frame.grid(row=0, column=2, rowspan=2, padx=20, sticky="nsew")

aggressive_var = tk.IntVar(value=0)
aggressive_check = tk.Checkbutton(
    balance_options_frame,
    text="Aggressive Balancing",
    variable=aggressive_var,
    bg=PANEL_BG,
    fg=TEXT_COLOR,
    selectcolor=DARK_BG,
    activebackground=PANEL_BG,
    activeforeground=ACCENT,
    font=small_font
)
aggressive_check.pack(anchor="w", pady=5)

auto_balance_var = tk.IntVar(value=1)
auto_balance_check = tk.Checkbutton(
    balance_options_frame,
    text="Auto Balance",
    variable=auto_balance_var,
    bg=PANEL_BG,
    fg=TEXT_COLOR,
    selectcolor=DARK_BG,
    activebackground=PANEL_BG,
    activeforeground=ACCENT,
    font=small_font
)
auto_balance_check.pack(anchor="w", pady=5)

# Manual balance button
manual_balance_button = tk.Button(
    balance_options_frame,
    text="Balance Now",
    command=lambda: manual_balance(),
    font=("Segoe UI", 10),
    bg=ACCENT,
    fg=DARK_BG,
    relief="flat",
    padx=10,
    pady=3
)
manual_balance_button.pack(anchor="w", pady=(10, 5))

def manual_balance():
    """Force a load balancing operation"""
    if not monitoring:
        log_action("⚠️ Cannot balance: Monitoring is not active")
        return
    
    cpu_loads = get_cpu_load()
    max_idx = cpu_loads.index(max(cpu_loads))
    min_idx = cpu_loads.index(min(cpu_loads))
    
    log_action(f"🔄 Manual balancing: CPU {max_idx} → CPU {min_idx}")
    perform_load_balancing(max_idx, min_idx)

# Function to manually balance a selected process
def balance_selected_process():
    """Balance the selected process in the process list"""
    if not monitoring:
        log_action("⚠️ Cannot balance: Monitoring is not active")
        return
        
    selection = process_list.curselection()
    if not selection:
        log_action("⚠️ No process selected")
        return
        
    # Get the selected process info
    process_info = process_list.get(selection[0])
    
    # Extract PID from the string
    try:
        pid_str = process_info.split("(PID: ")[1].split(")")[0]
        pid = int(pid_str)
        
        # Get current CPU loads
        cpu_loads = get_cpu_load()
        min_idx = cpu_loads.index(min(cpu_loads))
        
        # Set the process affinity to the least loaded CPU
        if set_process_affinity(pid, [min_idx]):
            process_name = process_info.split(" (PID:")[0]
            log_action(f"🔄 Manually moved process {process_name} to CPU {min_idx}")
            balanced_processes[pid] = time.time()  # Mark as recently balanced
        else:
            log_action("⚠️ Failed to set process affinity")
    except Exception as e:
        log_action(f"⚠️ Error: {str(e)}")

# Add right-click context menu for processes
def show_process_menu(event):
    try:
        selection = process_list.curselection()
        if selection:
            process_menu.post(event.x_root, event.y_root)
    except:
        pass

process_menu = tk.Menu(root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR, activebackground=ACCENT, activeforeground=DARK_BG)
process_menu.add_command(label="Balance This Process", command=balance_selected_process)

process_list.bind("<Button-3>", show_process_menu)  # Right-click

# Add a load generator for testing
def generate_load():
    """Generate CPU load for testing balancing"""
    try:
        log_action("🔄 Generating test load on CPU 0...")
        
        # Create a script that will generate load
        load_script = """
import time
import multiprocessing

def generate_load(cpu_num):
    # Pin this process to the specified CPU
    process = multiprocessing.current_process()
    process.cpu_affinity([cpu_num])
    
    # Generate load
    start_time = time.time()
    while time.time() - start_time < 30:  # Run for 30 seconds
        x = 0
        for i in range(10000000):
            x += i * i
            
if __name__ == '__main__':
    generate_load(0)  # Generate load on CPU 0
        """
        
        # Save to a temporary file
        with open("temp_load_generator.py", "w") as f:
            f.write(load_script)
            
        # Run the load generator in a separate process
        subprocess.Popen(["python", "temp_load_generator.py"])
        
        log_action("⚙️ Test load process started (will run for 30 seconds)")
    except Exception as e:
        log_action(f"⚠️ Error generating load: {str(e)}")

# Add a load generator button to settings
generate_load_button = tk.Button(
    balance_options_frame,
    text="Generate Test Load",
    command=generate_load,
    font=("Segoe UI", 10),
    bg=BORDER_COLOR,
    fg=TEXT_COLOR,
    relief="flat",
    padx=10,
    pady=3
)
generate_load_button.pack(anchor="w", pady=5)

# Show home frame initially
update_active_nav_button("home")
home_frame.pack(fill="both", expand=True)

# Initialize with a welcome message
log_action("Welcome to CPU Load Balancer Pro! Press Start to begin monitoring.")
log_action("This version includes REAL load balancing capabilities.")

# Start the main loop
root.mainloop()
