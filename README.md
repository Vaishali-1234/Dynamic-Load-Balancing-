# CPU Load Balancer (Threshold-Based with Prediction)

This project implements a dynamic CPU load balancer using a threshold-based algorithm with predictive capabilities. It monitors CPU usage, predicts potential overloads, and balances the load by simulating task movement between CPU cores.

## Features

* **Real-time CPU Monitoring:** Displays CPU usage for each core in a graphical interface.
* **Threshold-Based Load Balancing:** Balances the load when CPU usage exceeds or falls below predefined thresholds (L_HIGH and L_LOW).
* **Predictive Overload Detection:** Predicts potential overloads based on CPU usage history, aiming to prevent performance bottlenecks.
* **Graphical User Interface (GUI):** Provides an intuitive visual representation of CPU usage and load balancing actions using Tkinter and Matplotlib.
* **Logging:** Logs load balancing actions and monitoring status in a text area within the GUI.

## Algorithm

The load balancing algorithm uses the following steps:

1.  **CPU Load Retrieval:** Retrieves CPU usage for each core using `psutil`.
2.  **Overload Prediction:** Predicts potential overloads by analyzing the recent CPU usage history, calculating the average usage, and comparing it to a threshold.
3.  **Load Balancing:** If an overload is predicted or detected (usage exceeds `L_HIGH` or falls below `L_LOW`), the algorithm simulates moving tasks from the most loaded CPU to the least loaded CPU.
4.  **Visualization:** Displays CPU usage in a bar graph, highlighting overloaded and underloaded cores with different colors.
5.  **Logging:** Logs load balancing actions and monitoring status.

## Requirements

* Python 3.x
* `psutil` library: `pip install psutil`
* `matplotlib` library: `pip install matplotlib`
* `numpy` library: `pip install numpy`

## Usage

1.  Clone the repository: `git clone [repository URL]`
2.  Install the required libraries: `pip install -r requirements.txt`
3.  Run the Python script: `python your_script_name.py`
4.  Use the "Start" and "Stop" buttons in the GUI to control monitoring and load balancing.
5.  Observe the CPU usage graph and log messages displayed in the GUI.

## Project Structure

* `your_script_name.py`: The main Python script containing the load balancing logic and GUI.
* `requirements.txt`: Lists the Python packages required to run the project.
* `.gitignore`: Specifies files and directories that Git should ignore.
* `LICENSE`: Specifies the license under which the project is distributed (e.g., MIT License).

## Commit History

This project was developed in nine commits:

1.  **Initial Commit:** Basic structure and CPU load retrieval.
2.  **Second Commit:** Added thresholds and basic load balancing logic.
3.  **Third Commit:** Added predictive overload functionality.
4.  **Fourth Commit:** Added logging functions.
5.  **Fifth Commit:** Added basic graphing functions (no Tkinter).
6.  **Sixth Commit:** Added monitoring start/stop.
7.  **Seventh Commit:** Added basic GUI structure (Tkinter).
8.  **Eighth Commit:** Tkinter graphing integration.
9.  **Ninth Commit:** Final GUI packing and mainloop.

## Contributions

* Amal Krishna: Dashboard, graphical monitoring, UI design.
* Jens Mathew Thomas: Navigation, algorithm development.
* Vaishali V: Content, reports, user experience.

## License

This project is distributed under the MIT License. See the `LICENSE` file for more information.

## Future Enhancements

* Implement and compare different load balancing algorithms.
* Include monitoring of additional system resources (e.g., memory, disk I/O).
* Add more detailed logging and reporting.
* Enhance the GUI with more advanced visualizations and user controls.
* Add a more realistic simulation of task creation and movement.
* Add configuration options for the High and Low thresholds via the GUI.
* Add the ability to save log files.
