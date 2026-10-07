"""
Script de test / évaluation du modèle de qualité de conduite - 3 classes
===========================================================================

Recharge le modèle XGBoost (3 classes: safe_driving, risky_driving, danger)
et l'évalue avec un split par session (anti-fuite de données), en affichant
le rapport de classification et la matrice de confusion.

Prérequis :
    pip install pandas scikit-learn xgboost joblib matplotlib seaborn
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import joblib

from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

import matplotlib.pyplot as plt
import seaborn as sns


# ==============================
# Configuration
# ==============================

DATASET = "dataset_features_3classes.csv"
MODEL_FILE = "driving_quality_model_3classes.json"
ENCODER_FILE = "label_encoder_3classes.pkl"

FEATURES = [
    "adc_value",
    "distance_cm",
    "delta_adc",
    "delta_distance",
    "adc_speed",
    "distance_speed",
    "adc_mean",
    "distance_mean",
    "adc_std",
    "distance_std",
    "distance_min",
    "distance_max",
]

SESSION_COLUMN = "session_datetime"


# ==============================
# Chargement
# ==============================

df = pd.read_csv(DATASET)
print(f"Nombre de lignes chargées : {len(df)}")

encoder = joblib.load(ENCODER_FILE)

model = xgb.XGBClassifier()
model.load_model(MODEL_FILE)

X = df[FEATURES]
y_encoded = encoder.transform(df["label"])


def evaluate(y_true, y_pred, title):
    acc = accuracy_score(y_true, y_pred)
    print(f"\n===== {title} =====")
    print("Accuracy :", round(acc, 4))
    print("\nRapport de classification :")
    print(classification_report(y_true, y_pred, target_names=encoder.classes_))

    cm = confusion_matrix(y_true, y_pred)
    print("Matrice de confusion (brute) :")
    print(cm)

    plt.figure(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=encoder.classes_, yticklabels=encoder.classes_)
    plt.title(title)
    plt.ylabel("Vraie classe")
    plt.xlabel("Classe prédite")
    plt.tight_layout()
    fname = f"confusion_matrix_{title.replace(' ', '_')}.png"
    plt.savefig(fname)
    plt.close()
    print(f"Matrice de confusion sauvegardée : {fname}")

    return acc


# ==============================
# Split par session (honnête)
# ==============================

if SESSION_COLUMN not in df.columns:
    raise ValueError(
        f"Colonne '{SESSION_COLUMN}' introuvable dans {DATASET} — "
        "impossible de faire le split par session."
    )

groups = df[SESSION_COLUMN]

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y_encoded, groups=groups))

X_test = X.iloc[test_idx]
y_test = y_encoded[test_idx]

print(f"\nSessions de test : {groups.iloc[test_idx].nunique()}")
print(f"Lignes de test : {len(X_test)}")

y_pred = model.predict(X_test)
evaluate(y_test, y_pred, "Modele 3 classes - split par session")


# ==============================
# Test sur cas limites synthétiques (sanity check)
# ==============================
# Quelques exemples représentatifs de chaque classe, construits à la main,
# pour un contrôle rapide et lisible en plus de l'évaluation statistique.

print("\n===== Sanity check sur exemples représentatifs =====")

sanity_examples = [
    # (adc, dist, delta_adc, delta_dist, adc_speed, dist_speed,
    #  adc_mean, dist_mean, adc_std, dist_std, dist_min, dist_max, classe_attendue)
    (1500, 55, 20, 0.5, 0.13, 0.003, 1480, 54.5, 30, 1.0, 53, 56, "safe_driving"),
    (3800, 60, 3200, 1.0, 21.0, 0.006, 2200, 59, 1500, 1.5, 57, 62, "risky_driving"),
    (2000, 3, -50, -8, -0.33, -0.05, 2050, 6, 100, 2.0, 3, 10, "danger"),
]

rows = []
labels = []
for ex in sanity_examples:
    rows.append(list(ex[:12]))
    labels.append(ex[12])

X_sanity = pd.DataFrame(rows, columns=FEATURES)
preds_sanity = model.predict(X_sanity)
pred_labels = encoder.inverse_transform(preds_sanity)

for expected, predicted in zip(labels, pred_labels):
    status = "OK" if expected == predicted else "MISMATCH"
    print(f"  attendu={expected:15s} predit={predicted:15s} [{status}]")
