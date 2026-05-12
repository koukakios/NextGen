# NextGen — Multimodal Assistive Wheelchair Control Prototype

Early-stage Python project exploring multimodal wheelchair-control interfaces using biosignal processing and computer vision, with separate modules for perception, signal processing, mechatronics abstraction, and system integration.

## Project Status

This is an **early-stage prototype** and **research project**. The repository contains initial module structure and proof-of-concept code only. It is not a medical device, not safety-certified, and not intended for real wheelchair deployment yet.

> ⚠️ **Safety note:**  
> This repository is an early-stage software prototype. It is not a certified medical device, not safety validated, and must not be used to control a real wheelchair without proper hardware interlocks, emergency-stop mechanisms, clinical validation, and supervised testing.

## Motivation

Many assistive mobility systems rely on traditional joystick-based control, which may not be accessible for users with limited motor function. NextGen explores alternative human-machine interfaces by combining:

- **Biosignal-based intent detection**: Using EEG or EMG signals to infer user commands.
- **Camera-based head/eye/face-direction estimation**: Leveraging computer vision to detect gaze, head pose, or facial cues for directional intent.
- **Multimodal fusion**: Integrating biosignal and vision inputs for more robust and reliable command generation.

The project aims to prototype a modular framework for assistive robotics, focusing on safety-aware, multimodal control systems.

## High-Level Architecture

```
Camera / Vision Input          Biosignal Source
          |                           |
          v                           v
Computer Vision Pipeline      Biosignal Interface
          |                           |
          v                           v
Face / Eye / Head Features    Signal Processing / Features
          |                           |
          +------------+--------------+
                       |
                       v
          Multimodal Intent Estimation
                       |
                       v
          Safety Gate / Command Validation
                       |
                       v
          System Integration Layer
                       |
                       v
          Mechatronics / Wheelchair Control Abstraction
```

- **Camera / Vision Input & Biosignal Source**: Raw input streams from cameras and biosignal devices.
- **Computer Vision Pipeline & Biosignal Interface**: Initial processing and data acquisition.
- **Face / Eye / Head Features & Signal Processing / Features**: Feature extraction from vision and biosignal data.
- **Multimodal Intent Estimation**: Fusion of features to estimate user intent (e.g., turn left, move forward).
- **Safety Gate / Command Validation**: Validation and safety checks before command execution.
- **System Integration Layer**: Coordination between perception and control.
- **Mechatronics / Wheelchair Control Abstraction**: Abstracted control commands for wheelchair actuators.

## Computer Vision Scope

The computer vision module handles camera input and extracts intent cues from visual data:

- Camera input handling and frame capture.
- Face detection and tracking.
- Eye-region detection and gaze estimation.
- Head-pose estimation for directional cues.
- Generation of simple commands (left/right/forward/stop) based on visual features.
- Fallback logic when face or eyes are not detected.
- Future integration with biosignal confidence scores for multimodal reliability.

This component is currently planned or in early implementation stages.

## Biosignal Scope

The biosignal module manages physiological input for intent detection:

- Biosignal input interface for EEG/EMG devices.
- Preprocessing and filtering to clean raw signals.
- Artifact handling (e.g., noise, muscle interference).
- Feature extraction from processed signals.
- Simple command classification based on biosignal patterns.
- Planned experiments with EEG/EMG for validated control signals.

No clinically validated datasets or real-time acquisition are included yet.

## Repository Structure

- **Biosignals/**: Biosignal input interfaces, preprocessing, and data handling.
- **Signal Processing/**: Filtering, feature extraction, classical signal-processing methods, and ML experiments.
- **Mechatronics/**: Motor-control abstractions, actuator interfaces, and wheelchair movement commands.
- **System Integration/**: Connecting vision/biosignal intent estimation to mechatronic control logic.
- **computer_vision/**: Camera input, face/eye/head-pose estimation, and vision-based command cues.

## Planned Capabilities

- Camera-based face detection and tracking.
- Eye or gaze-direction estimation.
- Head-pose based command cues.
- Biosignal acquisition interface.
- Biosignal preprocessing pipeline.
- Filtering and artifact handling.
- Feature extraction and classification.
- Multimodal fusion between CV and biosignals.
- Safety-gated movement command generation.
- Simulated wheelchair control layer.
- Logging for experiments.
- Hardware abstraction layer.
- Unit tests for processing modules.

## Technical Focus

- Python architecture for modular prototyping.
- OpenCV-based perception pipeline planning.
- Face/eye/head-direction based intent estimation.
- Signal-processing pipeline design.
- Assistive robotics control abstraction.
- Safety-aware command gating.
- Modular human-machine interface design.
- Future embedded deployment potential.

## Current Limitations

- No clinically validated biosignal dataset included.
- No real-time acquisition pipeline yet.
- No physical wheelchair control yet.
- No clinical or safety validation.
- Computer-vision pipeline is early-stage or planned.
- Current modules are early placeholders.
- No guarantee of medical reliability.

## Getting Started

Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/koukakios/NextGen.git
cd NextGen
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# or
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Example Usage

Planned high-level pipeline:

```python
# Planned high-level pipeline

vision_features = vision_pipeline.extract_features(frame)
biosignal_features = biosignal_pipeline.extract_features(raw_signal)

command = fusion_layer.estimate_intent(
    vision_features=vision_features,
    biosignal_features=biosignal_features,
)

safe_command = safety_gate.validate(command)
wheelchair_controller.execute(safe_command)
```
