# ADAS Intelligent Driving Quality Assessment

## 1. Project Overview

This project presents an embedded intelligent ADAS prototype for **driving-quality assessment and risk detection**.

The system combines:

- STM32 embedded systems
- Sensor acquisition
- CAN bus communication
- Feature engineering
- XGBoost machine learning
- Real-time inference
- Embedded actuation
- Raspberry Pi-based processing

The processing chain is:

```text
Sensors → STM32 acquisition → CAN → AI processing
       → risk classification → CAN decision → embedded control
```

---

## 2. System Architecture

```text
                 ┌─────────────────────┐
                 │       Sensors       │
                 │ ADC + Ultrasonic    │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │     STM32 #1        │
                 │  Data Acquisition   │
                 │ ADC / TIM / GPIO    │
                 └──────────┬──────────┘
                            │
                            │ CAN
                            ▼
                 ┌─────────────────────┐
                 │     STM32 #2        │
                 │ CAN / Embedded      │
                 │ Control             │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Raspberry Pi / AI   │
                 │ Feature Engineering │
                 │ XGBoost Inference   │
                 └──────────┬──────────┘
                            │
                            │ Risk decision
                            ▼
                 ┌─────────────────────┐
                 │ Actuation / Alert   │
                 │ Servo / Outputs     │
                 └─────────────────────┘
```

---

## 3. Objectives

The project aims to:

- Acquire driving-related measurements from embedded sensors.
- Transfer measurements through CAN.
- Build a dataset from the acquired signals.
- Extract temporal and statistical features.
- Train a multiclass XGBoost classifier.
- Evaluate the model using session-based validation.
- Perform real-time inference.
- Generate a driving-risk level.
- Transmit the decision to the embedded control system.

---

## 4. Hardware

### STM32 #1 — Acquisition Node

The first STM32 is responsible for sensor acquisition:

- ADC for analog signal acquisition
- HC-SR04 ultrasonic sensor
- Timer-based distance measurement
- CAN communication
- Timestamp generation

### STM32 #2 — Control Node

The second STM32 handles CAN reception and embedded control.

| Peripheral | Function |
|---|---|
| CAN1 | CAN communication |
| USART2 | Debug / monitoring |
| TIM2 | Servo control |
| GPIO | Status / control outputs |

Relevant configuration used in the project:

```text
CAN1_RX   → PD0
CAN1_TX   → PD1
USART2_TX → PA2
USART2_RX → PA3
LED       → PB0
Servo     → TIM2 CH1 / PA0
```

The CAN bitrate is:

```text
500 kbit/s
```

### Processing Platform

A Raspberry Pi is used for the AI processing and real-time inference part of the prototype.

---

## 5. CAN Communication

### Acquisition Frame

The acquisition message uses:

```text
CAN ID : 0x001
DLC    : 8 bytes
```

Payload:

| Bytes | Information |
|---|---|
| 0–3 | Timestamp |
| 4–5 | ADC value |
| 6–7 | Distance |

### Decision Frame

The decision/control communication uses:

```text
CAN ID : 0x100
```

The first byte represents the risk level:

```text
0 → Safe
1 → Risky
2 → Danger
```

---

## 6. Dataset

The experimental dataset contains measurements acquired from the embedded system.

Main raw variables:

```text
timestamp_ms
adc_value
distance_cm
label
```

The measurements are organized into acquisition sessions using:

```text
session_datetime
```

Session-based organization is used to prevent measurements from the same session being distributed between training and testing.

---

## 7. Driving-Quality Classes

The final machine-learning pipeline uses three classes:

| Class | Meaning |
|---:|---|
| 0 | `danger` |
| 1 | `risky_driving` |
| 2 | `safe_driving` |

The label encoder is saved with the trained model to preserve the class mapping during inference.

---

## 8. Feature Engineering

A sliding window of:

```text
WINDOW_SIZE = 5
```

is used.

> Five represents five consecutive measurements, not five seconds.

### Temporal Features

For each session:

```text
delta_adc
delta_distance
delta_time
```

are calculated.

The following variation features are then derived:

```text
adc_speed
distance_speed
```

These represent variation per unit of the timestamp used by the dataset and should not be interpreted as physical m/s without an appropriate time calibration.

### Rolling Statistics

The five-sample window is used to calculate:

```text
adc_mean
distance_mean
adc_std
distance_std
distance_min
distance_max
```

The final 12 input features are:

```text
adc_value
distance_cm
delta_adc
delta_distance
adc_speed
distance_speed
adc_mean
distance_mean
adc_std
distance_std
distance_min
distance_max
```

---

## 9. XGBoost Model

The selected classifier is **XGBoost** configured for multiclass classification.

Main parameters:

```text
objective          = multi:softmax
n_estimators       = 200
max_depth          = 6
learning_rate      = 0.1
subsample          = 0.8
colsample_bytree   = 0.8
random_state       = 42
```

### Class Imbalance

Class weights are calculated from the number of samples in each class and supplied to XGBoost through `sample_weight`.

This reduces the influence of class imbalance during training.

---

## 10. Training / Test Split

The split is performed using:

```python
GroupShuffleSplit(
    n_splits=1,
    test_size=0.2,
    random_state=42
)
```

with:

```text
session_datetime
```

as the grouping variable.

Therefore, a complete acquisition session belongs either to the training set or to the test set.

---

## 11. Model Evaluation

The validation pipeline uses:

- Accuracy
- Precision
- Recall
- F1-score
- Confusion matrix

The evaluation script reloads the saved model and label encoder and reproduces the same session-based split.

A synthetic sanity check is also performed for:

```text
safe_driving
risky_driving
danger
```

This verifies that the saved model, encoder and inference pipeline remain compatible.

---

## 12. Real-Time Inference

The real-time inference pipeline uses the same feature structure as the training pipeline.

```text
CAN frame
   ↓
ADC + Distance extraction
   ↓
5-sample buffer
   ↓
Feature computation
   ↓
XGBoost inference
   ↓
Risk classification
   ↓
CAN decision message
```

The real-time application uses:

```text
CAN interface : vcan0
CAN ID        : 0x200
```

Payload:

```text
Bytes 0–1 → ADC value
Byte 2    → Distance
```

A five-measurement buffer is maintained before calculating the feature vector.

The inference pipeline reconstructs the same 12 features used during training.

If no CAN message is received for more than approximately one second, the buffers are reset.

---

## 13. Software Architecture

```text
┌──────────────────────────────────────────┐
│            Data Acquisition              │
│       STM32 + ADC + HC-SR04              │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│             CAN Communication            │
│               500 kbit/s                 │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│             Feature Engineering          │
│       Temporal + Statistical Features    │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│              XGBoost Model               │
│           3-Class Classification         │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│              Risk Decision               │
│        Safe / Risky / Danger             │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│             Embedded Control             │
│              Servo / GPIO                 │
└──────────────────────────────────────────┘
```

---

## 14. Technologies

### Embedded

- STM32
- STM32CubeIDE
- STM32CubeMX
- STM32 HAL
- C
- CAN
- ADC
- GPIO
- TIM
- USART

### Machine Learning

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost
- Matplotlib
- Seaborn

### Processing

- Raspberry Pi
- Linux
- SocketCAN / virtual CAN during development

---

## 15. Recommended Repository Structure

```text
ADAS-Driving-Quality/
│
├── README.md
│
├── STM32/
│   ├── STM32_Acquisition/
│   │   └── ...
│   │
│   └── STM32_Control/
│       └── ...
│
├── AI/
│   ├── data/
│   │   ├── dataset_3classes.csv
│   │   └── dataset_features_3classes.csv
│   │
│   ├── feature_engineering/
│   │   └── feature_engineering.py
│   │
│   ├── training/
│   │   └── train_xgboost.py
│   │
│   ├── evaluation/
│   │   └── sanity_check.py
│   │
│   └── models/
│       ├── driving_quality_model_3classes.json
│       └── label_encoder_3classes.pkl
│
├── RaspberryPi/
│   └── realtime_inference.py
│
├── docs/
│   ├── architecture/
│   ├── results/
│   └── images/
│
└── requirements.txt
```

Adapt the directory names to the actual repository before publishing.

---

## 16. Installation

Create a Python virtual environment:

```bash
python -m venv venv
```

Windows:

```bash
venv\Scriptsctivate
```

Linux / Raspberry Pi:

```bash
source venv/bin/activate
```

Install the required packages:

```bash
pip install numpy pandas scikit-learn xgboost matplotlib seaborn joblib python-can
```

---

## 17. Feature Engineering

Place the raw dataset in the expected data directory and execute the feature-engineering script.

The processing generates:

```text
dataset_features_3classes.csv
```

This dataset contains the features required by the XGBoost training pipeline.

---

## 18. Model Training

Run the training script:

```bash
python train_xgboost.py
```

The training process:

1. Loads the engineered dataset.
2. Encodes the target classes.
3. Performs a session-based 80/20 split.
4. Computes class weights.
5. Trains the XGBoost classifier.
6. Evaluates the model.
7. Generates evaluation information.
8. Saves the trained model and label encoder.

Generated files:

```text
driving_quality_model_3classes.json
label_encoder_3classes.pkl
```

---

## 19. Model Evaluation

Run the evaluation / sanity-check script:

```bash
python sanity_check.py
```

The script reloads the trained model and evaluates the classification pipeline using the same grouped split.

---

## 20. Real-Time CAN Inference

The real-time application expects the CAN interface:

```text
vcan0
```

Example Linux virtual CAN configuration:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Then launch:

```bash
python realtime_inference.py
```

The CAN interface can be adapted when using a physical CAN interface.

---

## 21. STM32 Firmware

The STM32 projects are developed with **STM32CubeIDE**.

For each STM32:

1. Open the corresponding CubeIDE project.
2. Verify the MCU and peripheral configuration.
3. Verify the CAN configuration.
4. Build the project.
5. Connect the ST-LINK debugger/programmer.
6. Flash the firmware.
7. Open the serial terminal when debugging is required.

Both nodes must use compatible CAN parameters, identifiers and payload formats.

---

## 22. End-to-End Execution

```text
1. Flash STM32 #1
        ↓
2. Flash STM32 #2
        ↓
3. Start CAN communication
        ↓
4. Start Raspberry Pi / AI processing
        ↓
5. Acquire sensor measurements
        ↓
6. Send CAN frames
        ↓
7. Build the 5-sample feature window
        ↓
8. Execute XGBoost inference
        ↓
9. Determine the risk level
        ↓
10. Send the decision through CAN
        ↓
11. Apply the corresponding embedded action
```

---

## 23. Development Methodology

### Step 1 — Embedded acquisition

Validation of:

- ADC acquisition
- Ultrasonic measurement
- Timestamp generation
- CAN transmission

### Step 2 — Dataset construction

Collection and organization of measurements into acquisition sessions.

### Step 3 — Feature engineering

Creation of temporal differences, variation features and rolling statistics.

### Step 4 — Machine learning

Training and validation of the XGBoost multiclass classifier.

### Step 5 — Real-time inference

Reproduction of the training feature pipeline on streaming CAN data.

### Step 6 — Embedded integration

Transmission of the risk decision back to the embedded control system.

---

## 24. Important Files

```text
dataset_3classes.csv
dataset_features_3classes.csv
driving_quality_model_3classes.json
label_encoder_3classes.pkl
```

The STM32 firmware projects contain the source code required to reproduce the embedded acquisition and control nodes.

---

## 25. Limitations

This project is an experimental embedded ADAS prototype.

The dataset is based on controlled measurements from the prototype sensors and does not represent the complete variability of real road-driving conditions.

The model should therefore not be considered a production automotive safety system.

Further validation would be required for:

- Real vehicle CAN signals
- Larger and more diverse datasets
- Hardware-in-the-loop testing
- Functional safety
- Automotive-grade validation
- Cybersecurity
- Robust fault handling

---

## 26. Future Improvements

Possible extensions include:

- Integration of real vehicle CAN data
- LiDAR and additional ultrasonic sensing
- Sensor fusion
- Larger and more representative datasets
- Hyperparameter optimization
- Embedded model optimization
- Direct deployment on embedded AI hardware
- Improved fault detection
- Hardware-in-the-loop validation
- Automotive cybersecurity mechanisms
- Real-time performance profiling

---

## 27. Project Objective

This project demonstrates an end-to-end integration of **embedded systems, CAN communication and machine learning** for intelligent driving-quality assessment.

The complete processing chain is:

```text
Sensors
   ↓
Embedded acquisition
   ↓
CAN communication
   ↓
Feature engineering
   ↓
XGBoost
   ↓
Risk classification
   ↓
CAN decision
   ↓
Embedded action
```

The architecture provides a foundation for further development toward advanced embedded ADAS and edge-AI applications.

---

## 28. Author

**Ilyes Ben Yanes**

Embedded Systems / Infotronics Engineering Student  
ENICarthage — Université de Carthage

LinkedIn: https://linkedin.com/in/ben-yanes-ilyes
