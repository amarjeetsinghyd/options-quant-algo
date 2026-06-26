import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ml_research.db")

class DriftDetector:
    """
    Concept Drift Detector.
    Tracks model drift by evaluating gamma-specific metrics:
    - gamma_recall (did we miss actual moves?)
    - false_gamma_prediction (are we predicting false triggers?)
    - missed_big_gamma_events (did a big explosion occur with <20% model probability?)
    """
    def __init__(self):
        pass

    def check_for_model_drift(self, model_name):
        """
        Queries the last 100 model predictions with actual outcomes
        to calculate recall, false alarms, and missed explosions.
        Returns drift warnings if thresholds are breached, else None.
        """
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Fetch the last 100 predictions with finalized outcomes
            cursor.execute("""
                SELECT gamma_5_probability, actual_result, gamma_20_probability
                FROM model_predictions 
                WHERE model_name = ? AND actual_result IS NOT NULL 
                ORDER BY timestamp DESC LIMIT 100
            """, (model_name,))
            results = cursor.fetchall()
            conn.close()
            
            if len(results) < 30:
                # Not enough data yet to reliably check drift
                return None
                
            total = len(results)
            
            # For simplicity, we assume:
            # - actual_result: 1 = Gamma hit target (e.g. >=5% move), 0 = Failed / dead move
            # - we count a positive prediction if model output probability >= 0.50 (50%)
            # - actual_result can also represent quality (0-4), where >=2 is gamma
            
            actual_gammas = [r for r in results if r[1] >= 2 or r[1] == 1]
            predicted_gammas = [r for r in results if r[0] >= 0.50]
            
            # 1. Recall: True Positives / Actual Positives
            true_positives = sum([1 for r in actual_gammas if r[0] >= 0.50])
            gamma_recall = (true_positives / len(actual_gammas)) if actual_gammas else 1.0
            
            # 2. False Gamma Prediction: False Positives / Total Predicted Positives
            false_positives = sum([1 for r in predicted_gammas if r[1] == 0])
            false_gamma_rate = (false_positives / len(predicted_gammas)) if predicted_gammas else 0.0
            
            # 3. Missed Big Gamma: Explosive moves (actual quality 4 or result indicating large jump) 
            # where model had low predicted probability (< 20%)
            big_gammas = [r for r in results if r[1] == 4]
            missed_big_gammas = sum([1 for r in big_gammas if r[0] < 0.20])
            
            warnings = []
            
            # Thresholds:
            # Recall drops below 60%
            if gamma_recall < 0.60:
                warnings.append(f"Drift Alert: {model_name} Gamma Recall fell to {gamma_recall*100:.1f}% (target: >60%). Model is missing bursts.")
                
            # False Positive rate exceeds 45%
            if false_gamma_rate > 0.45:
                warnings.append(f"Drift Alert: {model_name} False Gamma Predictions rose to {false_gamma_rate*100:.1f}% (target: <45%). Model is over-firing.")
                
            # Missed any explosive gammas
            if missed_big_gammas > 0:
                warnings.append(f"Drift Alert: {model_name} missed {missed_big_gammas} explosive (Quality 4) moves with <20% probability.")
                
            if warnings:
                return "\n".join(warnings)
                
            return None
            
        except Exception as e:
            print(f"[DriftDetector] Error checking for drift: {e}")
            return None
