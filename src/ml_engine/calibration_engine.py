import numpy as np

from src.utils.logger import get_logger
logger = get_logger("calibration_engine")


class ProbabilityCalibrationEngine:
    """
    ML output should represent real probability.
    If a model outputs 90% confidence, the actual hit rate must be near 90%.
    Supports separate calibration models for different gamma targets (5%, 10%, 20%).
    """
    def __init__(self):
        self.calibration_maps = {}  # {f"{model_name}_{target_name}": calibration_model}

    def calibrate_prediction(self, model_name, target_name, raw_probability):
        """
        Takes raw model output and scales it to true historical probability
        using pre-trained Platt Scaling or Isotonic Regression maps.
        """
        key = f"{model_name}_{target_name}"
        if key not in self.calibration_maps:
            return raw_probability
            
        calibrator = self.calibration_maps[key]
        try:
            # Assume calibrator is an IsotonicRegression or Platt scaling model
            calibrated = calibrator.predict(np.array([[raw_probability]]))[0]
            return float(calibrated)
        except Exception as e:
            logger.error(f"[CalibrationEngine] Error during calibration for {key}: {e}")
            return raw_probability

    def train_calibration(self, model_name, target_name, raw_predictions, true_labels, method='isotonic'):
        """
        Called during model training to fit calibrator.
        method: 'sigmoid' (Platt scaling) or 'isotonic'
        """
        key = f"{model_name}_{target_name}"
        try:
            from sklearn.calibration import CalibratedClassifierCV
            from sklearn.isotonic import IsotonicRegression
            
            if method == 'isotonic':
                calibrator = IsotonicRegression(out_of_bounds='clip')
                calibrator.fit(raw_predictions, true_labels)
                self.calibration_maps[key] = calibrator
                logger.info(f"[CalibrationEngine] Trained Isotonic calibrator for {key}.")
            else:
                # Platt Scaling (logistic regression wrapper)
                from sklearn.linear_model import LogisticRegression
                calibrator = LogisticRegression()
                calibrator.fit(raw_predictions.reshape(-1, 1), true_labels)
                self.calibration_maps[key] = calibrator
                logger.info(f"[CalibrationEngine] Trained Platt calibrator for {key}.")
        except Exception as e:
            logger.info(f"[CalibrationEngine] Failed training calibrator for {key}: {e}")
