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
import traceback

# Thresholds
L_HIGH = 70  
L_LOW = 30   # Standard threshold
BALANCE_COOLDOWN = 15  # Seconds between balancing same process
MIN_CPU_USAGE = 2.0    # Minimum % CPU for consideration
monitoring = False
cpu_history = []
balanced_processes = {}  # Keep track of processes we've already balanced


# Update the color palette with more vibrant, cyberpunk-inspired colors
DARK_BG = "#0a0612"         # Deep void black (like the abyss)
PANEL_BG = "#1a1426"        # Dark purple (Shadow Garden robes)
ACCENT = "#ff0055"          # Blood red (I AM ATOMIC glow)
ACCENT_ALT = "#9900ff"      # Purple (magic circles)
TEXT_COLOR = "#e0d6ff"      # Soft white/purple (mystic glow)
HIGHLIGHT = "#ff5555"       # Bright red (danger)
SUCCESS = "#00cc88"         # Emerald (healing magic)
NEUTRAL = "#6a5acd"         # Slate purple (neutral)
BORDER_COLOR = "#3a2a5a"    # Darkened purple (gothic borders)

# Add these new functions for visual effects
def create_glow_effect(widget, color):
    """Adds a subtle glow effect to widgets"""
    widget.config(
        highlightbackground=color,
        highlightcolor=color,
        highlightthickness=2,
        relief="flat",
        borderwidth=0
    )

def animate_gradient(canvas, width, height):
    """Creates an animated gradient background"""
    colors = ["#0a0612", "#1a1426", "#2a1e3a", "#3a2850"]
    for i in range(len(colors)):
        canvas.create_rectangle(
            0, i*height/len(colors), 
            width, (i+1)*height/len(colors)),
def create_neumorphic_button(parent, text, command):
    """Creates a modern neumorphic button"""
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=("Segoe UI", 12, "bold"),
        bg=PANEL_BG,
        fg=TEXT_COLOR,
        relief="flat",
        borderwidth=0,
        activebackground=ACCENT,
        activeforeground=DARK_BG,
        padx=20,
        pady=10
    )
    
    # Add shadow effects
    shadow = tk.Frame(parent, bg=ACCENT_ALT)
    shadow.place(in_=btn, relx=0, rely=0.05, relwidth=1, relheight=1)
    shadow.lower(btn)
    
    return btn


def get_cpu_load():
    """Get per-core CPU usage"""
    try:
        return psutil.cpu_percent(percpu=True)
    except Exception as e:
        print(f"Error getting CPU load: {e}")
        return [0] * psutil.cpu_count()

def predict_overload():
    """Predict which core is likely to overload"""
    if len(cpu_history) < 5:
        return None
    try:
        avg_usage = np.mean(cpu_history[-5:], axis=0)
        for i, usage in enumerate(avg_usage):
            if usage > L_HIGH - 10:
                return i
        return None
    except Exception as e:
        log_action(f"Error in prediction algorithm: {e}")
        return None

def get_core_processes():
    """Get all CPU-intensive processes"""
    processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                if proc.info['cpu_percent'] > 1.0:  # Filter out idle processes
                    processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Sort by CPU usage (highest first)
        processes.sort(key=lambda p: p.info['cpu_percent'], reverse=True)
        return processes
    except Exception as e:
        log_action(f"Error getting processes: {e}")
        return []


def can_balance_process(proc):
    """Check if a process is suitable for migration"""
    try:
        # Skip PID 0 (System Idle) and negative PIDs
        if proc.pid <= 0:
            return False
            
        # Skip system/low-PID processes
        if proc.pid < 10:  # More aggressive system process blocking
            return False
            
        # Skip recently balanced processes
        if proc.pid in balanced_processes and time.time() - balanced_processes[proc.pid] < 30:
            return False
            
        # Skip critical system processes
        system_processes = ['system', 'systemd', 'kernel', 'wininit', 'services.exe', 
                           'explorer.exe', 'csrss.exe', 'lsass.exe', 'winlogon.exe',
                           'svchost.exe', 'taskhost.exe', 'dwm.exe']
        proc_name = proc.name().lower()
        if any(sys_proc in proc_name for sys_proc in system_processes):
            return False
            
        # Only processes using >1% CPU
        if proc.info['cpu_percent'] < 1.0:
            return False
            
        # Additional check for process status
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
            
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    except Exception as e:
        log_action(f"Unexpected error checking process {proc.pid if 'proc' in locals() else 'N/A'}: {str(e)}")
        return False
def set_process_affinity(pid, cpu_list):
    """Set CPU affinity for a process with enhanced error handling"""
    try:
        process = psutil.Process(pid)
        
        # Check process status first
        if process.status() == psutil.STATUS_ZOMBIE:
            raise ValueError("Process is a zombie")
            
        current_affinity = process.cpu_affinity()
        
        # Don't change if it's already set correctly
        if set(cpu_list) == set(current_affinity):
            return False
            
        # Additional check for system processes with special affinity
        if len(current_affinity) == 0:  # Some system processes return empty list
            raise ValueError("Process has special affinity settings")
            
        # Try to set new affinity
        process.cpu_affinity(cpu_list)
        
        # Verify the change took effect
        new_affinity = process.cpu_affinity()
        if set(new_affinity) != set(cpu_list):
            raise RuntimeError("Affinity change verification failed")
            
        return True
        
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        log_action(f"Permission error setting affinity for PID {pid}: {str(e)}")
        return False
    except Exception as e:
        log_action(f"Error setting affinity for PID {pid}: {str(e)}")
        return False

def perform_load_balancing(overloaded_core, underloaded_core, max_retries=2):
    """Improved process migration with retries"""
    retries = 0
    while retries < max_retries:
        try:
            processes = get_core_processes()
            processes.sort(key=lambda p: (p.info['cpu_percent'], p.nice() if hasattr(p, 'nice') else 0), reverse=True)
            
            for proc in processes:
                if can_balance_process(proc):
                    try:
                        if set_process_affinity(proc.pid, [underloaded_core]):
                            balanced_processes[proc.pid] = time.time()
                            log_action(f"✅ Successfully moved {proc.name()} (PID: {proc.pid}) to CPU {underloaded_core}")
                            return True
                    except Exception as e:
                        log_action(f"⚠️ Failed to move {proc.name()}: {str(e)}")
                        continue
                        
            log_action("🔍 No suitable processes found for migration")
            return False
            
        except Exception as e:
            retries += 1
            if retries >= max_retries:
                log_action(f"💥 Critical balancing error after {max_retries} retries: {str(e)}")
                return False
            time.sleep(0.5)  # Brief delay before retry

def balance_load(cpu_loads):
    try:
        if not (monitoring and auto_balance_var.get()):
            return None, None

        max_idx = cpu_loads.index(max(cpu_loads))
        min_idx = cpu_loads.index(min(cpu_loads))
        
        # More flexible threshold checking
        if (cpu_loads[max_idx] > L_HIGH and 
            cpu_loads[min_idx] < L_LOW and
            abs(cpu_loads[max_idx] - cpu_loads[min_idx]) > 30):  # Minimum difference
            
            log_action(f"⚖️ Strong imbalance detected: CPU {max_idx} ({cpu_loads[max_idx]:.1f}%) → CPU {min_idx} ({cpu_loads[min_idx]:.1f}%)")
            
            # Get movable processes sorted by best candidates
            processes = sorted(
                [p for p in get_core_processes() if can_balance_process(p)],
                key=lambda p: (p.info['cpu_percent'], p.nice() if hasattr(p, 'nice') else 0),
                reverse=True
            )
            
            if processes:
                proc = processes[0]  # Take the best candidate
                if set_process_affinity(proc.pid, [min_idx]):
                    balanced_processes[proc.pid] = time.time()
                    log_action(f"✅ Balanced {proc.name()} (PID: {proc.pid}, {proc.info['cpu_percent']:.1f}%) to CPU {min_idx}")
                    return max_idx, min_idx
                else:
                    log_action("⚠️ Failed to set affinity")
            else:
                log_action("🔍 No movable processes found")
        
        return None, None
        
    except Exception as e:
        log_action(f"💥 Balance error: {str(e)}")
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

    # Only perform balancing if auto-balance is enabled
    if auto_balance_var.get():
        max_idx, min_idx = balance_load(cpu_loads)
    else:
        max_idx, min_idx = None, None
    
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

# Manual balancing function
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

# Add a load generator for testing
import multiprocessing
import time

# Define burn_cpu OUTSIDE generate_load (critical for multiprocessing)
def burn_cpu(seconds):
    """CPU burner function (must be at module level)"""
    start = time.time()
    while time.time() - start < seconds:
        sum(x * x for x in range(1_000_000))  # Pure CPU torture

def generate_load():
    """Generate CPU load across all cores (30 seconds)"""
    try:
        log_action("💣 NUKE MODE: Generating brutal CPU load on ALL CORES for 30 sec...")
        
        workers = multiprocessing.cpu_count()
        processes = []
        for _ in range(workers):
            p = multiprocessing.Process(target=burn_cpu, args=(30,))
            p.start()
            processes.append(p)
        
        log_action("☠️ SUCCESS: CPU is now on FIRE (30 sec of pain).")
        
    except Exception as e:
        log_action(f"💀 FAILED TO NUKE CPU: {str(e)}")

# Set up the main window
root = tk.Tk()
root.title("⚡Quantum CoreMatrix🔥")
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
nav_frame = tk.Frame(root, bg="black", height=70)
nav_frame.pack(fill="x", side="top")
separator = tk.Frame(nav_frame, height=2, bg=ACCENT)
separator.pack(fill="x", side="bottom")

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
title_canvas = tk.Canvas(home_content, bg=DARK_BG, height=100, width=800, highlightthickness=0)
title_canvas.pack(pady=(40, 20))
# for i in range(5):
#     offset = i * 2
#     title_canvas.create_text(
#         400 + offset, 50 + offset,
#         text="CPU LOAD BALANCER PRO",
#         font=("Segoe UI", 36, "bold"),
#         fill=f"#{hex(255 - i*30)[2:]}{hex(100 + i*30)[2:]}{hex(255 - i*10)[2:]}"
#     )

title_canvas.create_text(350, 40, text="QUANTUM COREMATRIX", font=title_font, fill=ACCENT)

# Subtitle with animation effect
subtitle_label = tk.Label(home_content, text="Optimize Your System's Performance", fg=TEXT_COLOR, bg=DARK_BG, font=subtitle_font)
subtitle_label.pack(pady=(10, 40))

# Card-style info boxes
info_container = tk.Frame(home_content, bg=DARK_BG)
info_container.pack(fill="both", expand=True, pady=20)
info_container.grid_columnconfigure(0, weight=1)
info_container.grid_columnconfigure(1, weight=1)

def create_3d_card(parent):
    card = tk.Frame(
        parent,
        bg=PANEL_BG,
        padx=25,
        pady=25,
        relief="flat",
        borderwidth=0
    )
    
    # Create shadow
    shadow = tk.Frame(
        parent,
        bg=ACCENT_ALT,
        padx=25,
        pady=25
    )
    shadow.place(in_=card, relx=0.02, rely=0.02, relwidth=1, relheight=1)
    shadow.lower(card)
    
    return card
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

# # Main action button 
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
    height=5,
    relief="flat",
    borderwidth=0
)
proceed_button.pack()


# Hover effects
def on_enter(e):
    proceed_button.config(bg=ACCENT_ALT)
   

def on_leave(e):
    proceed_button.config(bg=ACCENT)

proceed_button.bind("<Enter>", on_enter)
proceed_button.bind("<Leave>", on_leave)

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
        "desc": "Created the dashboard interface and real-time monitoring visualizations. Modified the Algorithm to provide load generating function and anual balancing function",
        "emoji": "🎨"
    },
    {
        "name": "Jens Mathew Thomas",
        "role": "Algorithm Developer",
        "desc": "Implemented the predictive load balancing system and navigation logic. Added Log screen systems and modified the algorithm for optimised balancing",
        "emoji": "⚙️"
    },
    {
        "name": "Vaishali V",
        "role": "Content & UX Specialist",
        "desc": "Designed the user experience workflow and created documentation. Launched the pathway for administration access and implemented auto-balancing load for cpu",
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

# In your dashboard setup code:
dashboard_top = tk.Frame(dashboard_frame, bg=DARK_BG)
dashboard_top.pack(fill="x", pady=10)

# Split main content area
viz_frame = tk.Frame(dashboard_frame, bg=DARK_BG)
viz_frame.pack(fill="both", expand=True)

# Left column - Existing bar chart
graph_panel = tk.Frame(viz_frame, bg=PANEL_BG, padx=15, pady=15)
graph_panel.pack(side="left", fill="both", expand=True)

# Right column - New pie chart
pie_panel = tk.Frame(viz_frame, bg=PANEL_BG, padx=15, pady=15)
pie_panel.pack(side="right", fill="both", expand=True)

# Pie chart header
tk.Label(pie_panel, text="CPU Core Distribution", font=("Segoe UI", 14, "bold"), 
        bg=PANEL_BG, fg=ACCENT).pack()
status_bar = tk.Frame(dashboard_top, bg=PANEL_BG, padx=15, pady=10)
status_bar.pack(fill="x", pady=10)

# Status label
status_label = tk.Label(status_bar, text="Status: Inactive", font=("Segoe UI", 12), bg=PANEL_BG, fg=HIGHLIGHT)
status_label.pack(side="left", padx=10)

# Auto-balance toggle
auto_balance_var = tk.BooleanVar(value=True)
auto_balance_check = tk.Checkbutton(
    status_bar,
    text="Auto-Balance",
    variable=auto_balance_var,
    font=("Segoe UI", 12),
    bg=PANEL_BG,
    fg=TEXT_COLOR,
    selectcolor=DARK_BG,
    activebackground=PANEL_BG,
    activeforeground=ACCENT
)
auto_balance_check.pack(side="left", padx=20)

# Control buttons
controls_frame = tk.Frame(status_bar, bg=PANEL_BG)
controls_frame.pack(side="right", padx=10)

start_button = tk.Button(
    controls_frame,
    text="Start",
    command=start_monitoring,
    font=("Segoe UI", 11),
    bg=SUCCESS,
    fg=DARK_BG,
    padx=15,
    relief="flat"
)
start_button.pack(side="left", padx=5)

stop_button = tk.Button(
    controls_frame,
    text="Stop",
    command=stop_monitoring,
    font=("Segoe UI", 11),
    bg=HIGHLIGHT,
    fg=DARK_BG,
    padx=15,
    relief="flat",
    state=tk.DISABLED
)
stop_button.pack(side="left", padx=5)

clear_button = tk.Button(
    controls_frame,
    text="Clear Log",
    command=clear_log,
    font=("Segoe UI", 11),
    bg=NEUTRAL,
    fg=DARK_BG,
    padx=15,
    relief="flat"
)
clear_button.pack(side="left", padx=5)

# Dashboard content section (split into left and right panels)
dashboard_content = tk.Frame(dashboard_frame, bg=DARK_BG)
dashboard_content.pack(fill="both", expand=True, padx=20, pady=(0, 20))

# CPU Graph Panel (Left)
graph_panel = tk.Frame(dashboard_content, bg=PANEL_BG, padx=15, pady=15)
graph_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

graph_header = tk.Label(graph_panel, text="CPU Load Monitor", font=("Segoe UI", 14, "bold"), bg=PANEL_BG, fg=ACCENT)
graph_header.pack(pady=(0, 10))

# Create matplotlib figure and embed in tkinter
fig = Figure(figsize=(10, 4), dpi=100)
ax = fig.add_subplot(111)
canvas = FigureCanvasTkAgg(fig, master=graph_panel)
canvas.get_tk_widget().pack(fill="both", expand=True)
ax.spines['bottom'].set_color(ACCENT)
ax.spines['left'].set_color(ACCENT)
ax.tick_params(axis='x', colors=ACCENT)
ax.tick_params(axis='y', colors=ACCENT)
ax.grid(color=ACCENT_ALT, alpha=0.2)

# Advanced controls panel
advanced_controls = tk.Frame(graph_panel, bg=PANEL_BG, pady=10)
advanced_controls.pack(fill="x", pady=(10, 0))

balance_button = tk.Button(
    advanced_controls,
    text="Force Balance",
    command=manual_balance,
    font=("Segoe UI", 10),
    bg=ACCENT_ALT,
    fg=DARK_BG,
    relief="flat"
)
balance_button.pack(side="left", padx=5)

test_button = tk.Button(
    advanced_controls,
    text="Generate Test Load",
    command=generate_load,
    font=("Segoe UI", 10),
    bg=ACCENT_ALT,
    fg=DARK_BG,
    relief="flat"
)
test_button.pack(side="left", padx=5)

# Right panel (process list and log)
right_panel = tk.Frame(dashboard_content, bg=DARK_BG)
right_panel.pack(side="right", fill="both", expand=True, padx=(10, 0))

# Process list panel
process_panel = tk.Frame(right_panel, bg=PANEL_BG, padx=15, pady=15)
process_panel.pack(fill="both", expand=True, pady=(0, 10))

process_header = tk.Label(process_panel, text="Active Processes", font=("Segoe UI", 14, "bold"), bg=PANEL_BG, fg=ACCENT)
process_header.pack(pady=(0, 10))

process_frame = tk.Frame(process_panel, bg=PANEL_BG)
process_frame.pack(fill="both", expand=True)

process_list = tk.Listbox(
    process_frame,
    font=("Consolas", 9),
    bg=DARK_BG,
    fg=TEXT_COLOR,
    selectbackground=ACCENT,
    selectforeground=DARK_BG,
    height=10
)
process_list.pack(side="left", fill="both", expand=True)

process_scroll = tk.Scrollbar(process_frame, orient="vertical", command=process_list.yview)
process_scroll.pack(side="right", fill="y")
process_list.config(yscrollcommand=process_scroll.set)

# Button to balance selected process
balance_process_button = tk.Button(
    process_panel,
    text="Balance Selected Process",
    command=balance_selected_process,
    font=("Segoe UI", 10),
    bg=ACCENT_ALT,
    fg=DARK_BG,
    relief="flat"
)
balance_process_button.pack(pady=(10, 0))

# Log panel
log_panel = tk.Frame(right_panel, bg=PANEL_BG, padx=15, pady=15)
log_panel.pack(fill="both", expand=True)

log_header = tk.Label(log_panel, text="Activity Log", font=("Segoe UI", 14, "bold"), bg=PANEL_BG, fg=ACCENT)
log_header.pack(pady=(0, 10))

log_frame = tk.Frame(log_panel, bg=PANEL_BG)
log_frame.pack(fill="both", expand=True)

log_text = tk.Text(
    log_frame,
    font=("Consolas", 9),
    bg=DARK_BG,
    fg=TEXT_COLOR,
    height=10,
    wrap="word"
)
log_text.pack(side="left", fill="both", expand=True)

log_scroll = tk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
log_scroll.pack(side="right", fill="y")
log_text.config(yscrollcommand=log_scroll.set)

# Initially show the home page
show_home()

# Add window icon if available
try:
    root.iconbitmap("cpu_icon.ico")
except:
    pass

# Add welcome message to log
log_text.insert(tk.END, "Welcome to CPU Load Balancer Pro!\n")
log_text.insert(tk.END, "Click 'Start' to begin monitoring CPU cores.\n")
log_text.insert(tk.END, "-------------------------------\n")

# Start the main event loop
root.mainloop()

# Clean up temporary files
try:
    if os.path.exists("temp_load_generator.py"):
        os.remove("temp_load_generator.py")
except:
    pass
def pulse_status():
    current_color = status_label.cget("fg")
    if current_color == SUCCESS:
        status_label.config(fg=ACCENT_ALT)
    else:
        status_label.config(fg=SUCCESS)
    root.after(1000, pulse_status)

    pulse_status()
def on_enter(e):
    e.widget.config(bg=ACCENT, fg=DARK_BG)
    e.widget.master.config(bg=ACCENT)  # For shadow effect

def on_leave(e):
    e.widget.config(bg=PANEL_BG, fg=TEXT_COLOR)
    e.widget.master.config(bg=ACCENT_ALT)  # For shadow effect

for btn in [start_button, stop_button, balance_button, test_button]:
    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)

# Add typing animation to the welcome message
def type_writer(text, widget, delay=50):
    for i in range(len(text) + 1):
        widget.insert("end", text[:i])
        widget.delete(i, "end")
        widget.see("end")
        widget.update()
        time.sleep(delay/1000)