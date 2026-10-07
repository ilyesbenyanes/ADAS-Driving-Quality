import pandas as pd
import xgboost as xgb

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

import joblib


# ==============================
# Configuration
# ==============================

DATASET = "dataset_features_3classes.csv"

MODEL_FILE = "driving_quality_model_3classes.json"
ENCODER_FILE = "label_encoder_3classes.pkl"


# ==============================
# Chargement dataset
# ==============================

df = pd.read_csv(DATASET)

print("Nombre de données :", len(df))


# ==============================
# Séparation X / y
# ==============================

features = [
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
    "distance_max"
]


X = df[features]

y = df["label"]


# ==============================
# Encodage des labels
# ==============================

encoder = LabelEncoder()

y_encoded = encoder.fit_transform(y)


print("\nClasses :")
for i, c in enumerate(encoder.classes_):
    print(i, "->", c)


# Sauvegarde encodeur

joblib.dump(
    encoder,
    ENCODER_FILE
)


# ==============================
# Séparation train / test PAR SESSION
# ==============================
# Important : un split aléatoire ligne par ligne fuit des informations entre
# train et test car les lignes consécutives d'une même session sont très
# corrélées (mesures à 150ms d'intervalle). On regroupe donc par session
# avant de séparer.

if "session_datetime" not in df.columns:
    raise ValueError(
        "La colonne 'session_datetime' est absente de "
        f"{DATASET}. Assure-toi que ton script de feature engineering "
        "la conserve dans le fichier de sortie."
    )

from sklearn.model_selection import GroupShuffleSplit

groups = df["session_datetime"]

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y_encoded, groups=groups))

X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y_encoded[train_idx], y_encoded[test_idx]

print(f"\nSessions train: {groups.iloc[train_idx].nunique()} | "
      f"Sessions test: {groups.iloc[test_idx].nunique()}")
print(f"Lignes train: {len(X_train)} | Lignes test: {len(X_test)}")


# ==============================
# Calcul des poids des classes
# ==============================

class_counts = pd.Series(y_train).value_counts()

total = len(y_train)
n_classes = len(class_counts)


class_weights = {
    cls: total / (n_classes * count)
    for cls, count in class_counts.items()
}


print("\nPoids des classes :")
print(class_weights)


sample_weights = pd.Series(y_train).map(class_weights)


# ==============================
# Création du modèle XGBoost
# ==============================

model = xgb.XGBClassifier(

    objective="multi:softmax",

    num_class=len(encoder.classes_),

    n_estimators=200,

    max_depth=6,

    learning_rate=0.1,

    subsample=0.8,

    colsample_bytree=0.8,

    random_state=42

)


# ==============================
# Entraînement
# ==============================

print("\nEntraînement en cours...")

model.fit(
    X_train,
    y_train,
    sample_weight=sample_weights
)


print("Entraînement terminé")


# ==============================
# Evaluation
# ==============================

y_pred = model.predict(X_test)


accuracy = accuracy_score(
    y_test,
    y_pred
)


print("\nAccuracy (split par session) :", accuracy)


print("\nRapport de classification :")

print(
    classification_report(
        y_test,
        y_pred,
        target_names=encoder.classes_
    )
)


print("\nMatrice de confusion :")

print(
    confusion_matrix(
        y_test,
        y_pred
    )
)


# ==============================
# Importance des features
# ==============================

print("\nImportance des features (gain) :")
importance = model.get_booster().get_score(importance_type="gain")
for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
    print(f"  {feat}: {score:.2f}")


# ==============================
# Sauvegarde modèle
# ==============================

model.save_model(
    MODEL_FILE
)


print("\nModèle sauvegardé :", MODEL_FILE)
