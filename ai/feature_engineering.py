import pandas as pd
import numpy as np

# ==========================================
# CONFIGURATION
# ==========================================

INPUT_FILE = "dataset_3classes.csv"
OUTPUT_FILE = "dataset_features_3classes.csv"

WINDOW_SIZE = 5   # nombre de mesures utilisées pour les moyennes glissantes

# ==========================================


print("Chargement du dataset...")

df = pd.read_csv(INPUT_FILE)

print("Nombre de lignes avant feature engineering :", len(df))


# ==========================================
# Trier les données
# ==========================================

df = df.sort_values(
    by=["session_datetime", "timestamp_ms"]
)


# ==========================================
# Fonction de création des features
# par session
# ==========================================

def create_features(group):

    # Copie pour éviter les warnings pandas
    group = group.copy()

    # ------------------------------
    # Variations
    # ------------------------------

    group["delta_adc"] = group["adc_value"].diff()

    group["delta_distance"] = group["distance_cm"].diff()

    group["delta_time"] = group["timestamp_ms"].diff()


    # Eviter division par zéro
    group["delta_time"] = group["delta_time"].replace(0, np.nan)


    # ------------------------------
    # Vitesses de variation
    # ------------------------------

    group["adc_speed"] = (
        group["delta_adc"] /
        group["delta_time"]
    )


    group["distance_speed"] = (
        group["delta_distance"] /
        group["delta_time"]
    )


    # ------------------------------
    # Moyennes glissantes
    # ------------------------------

    group["adc_mean"] = (
        group["adc_value"]
        .rolling(WINDOW_SIZE)
        .mean()
    )


    group["distance_mean"] = (
        group["distance_cm"]
        .rolling(WINDOW_SIZE)
        .mean()
    )


    # ------------------------------
    # Ecart-types glissants
    # ------------------------------

    group["adc_std"] = (
        group["adc_value"]
        .rolling(WINDOW_SIZE)
        .std()
    )


    group["distance_std"] = (
        group["distance_cm"]
        .rolling(WINDOW_SIZE)
        .std()
    )


    # ------------------------------
    # Min / Max distance
    # ------------------------------

    group["distance_min"] = (
        group["distance_cm"]
        .rolling(WINDOW_SIZE)
        .min()
    )


    group["distance_max"] = (
        group["distance_cm"]
        .rolling(WINDOW_SIZE)
        .max()
    )


    return group



# ==========================================
# Application par session
# ==========================================
# Note : on utilise une boucle explicite plutôt que groupby().apply(),
# car les versions récentes de pandas (2.2+) excluent par défaut la
# colonne de groupement (session_datetime) du sous-DataFrame transmis
# à la fonction appliquée, ce qui la faisait disparaître du résultat final.

frames = []

for session_id, group in df.groupby("session_datetime", sort=False):
    frames.append(create_features(group))

df = pd.concat(frames, ignore_index=False)


# ==========================================
# Supprimer les lignes incomplètes
# causées par diff() et rolling()
# ==========================================

df = df.dropna()


# Réinitialiser l'index

df = df.reset_index(drop=True)


# ==========================================
# Sauvegarde
# ==========================================

df.to_csv(
    OUTPUT_FILE,
    index=False
)


print("\n========== FEATURE ENGINEERING ==========")

print("Nombre de lignes après création des features :", len(df))


print("\nNouvelles colonnes :")

for col in df.columns:
    print(col)


print("\nAperçu :")
print(df.head())


print("\nDataset sauvegardé :",
      OUTPUT_FILE)
print("\nRépartition des classes :")
print(df["label"].value_counts())
