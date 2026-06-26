class EnsembleEngine:
    """
    Do not allow one model winner. Models vote.
    Future decision should come from model council.
    """
    def __init__(self):
        # Weights can be adjusted based on historical walk-forward accuracy
        self.model_weights = {
            "LightGBM": 0.40,
            "XGBoost": 0.35,
            "CatBoost": 0.15,
            "RandomForest": 0.10
        }

    def compute_final_gamma_score(self, model_predictions):
        """
        Takes a dict of predictions: {"LightGBM": 88.0, "XGBoost": 82.0, ...}
        Returns the weighted ensemble Final Gamma Score.
        """
        total_score = 0.0
        total_weight = 0.0
        
        for model_name, score in model_predictions.items():
            # If the model is in our weight dict, use it, else give it equal small weight
            weight = self.model_weights.get(model_name, 0.10)
            total_score += score * weight
            total_weight += weight
            
        if total_weight == 0:
            return 0.0
            
        return round(total_score / total_weight, 2)
