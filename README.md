# Transtech Bill Desk

Python Streamlit app for Ubiquity Transtech. Upload Bisleri invoice photos or PDFs, extract trip rows, match customers and freight, then download Excel and a monthly billing statement.

This is the permanent app. Deploy it on **Streamlit Cloud** to get a lasting public link.

## Run on your computer

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Put your Gemini key in `.streamlit/secrets.toml`:

```toml
GOOGLE_API_KEY = "your_real_key"
```

```bash
streamlit run app.py
```

## Permanent website (GitHub + Streamlit Cloud)

You need a GitHub account. The API key stays private in Streamlit secrets, not in GitHub.

### 1. Put the code on GitHub

On your computer, inside this folder:

```bash
git init
git add .
git commit -m "Transtech Bill Desk"
```

Create a new **empty** GitHub repository, for example `transtech-bill-desk`.

Do **not** upload `.streamlit/secrets.toml`. It is already in `.gitignore`.

```bash
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/transtech-bill-desk.git
git push -u origin main
```

### 2. Deploy on Streamlit Cloud

1. Open [https://share.streamlit.io](https://share.streamlit.io)
2. Sign in with GitHub
3. Click **Create app**
4. Repository: `YOUR_USERNAME/transtech-bill-desk`
5. Branch: `main`
6. Main file: `app.py`
7. Open **Advanced settings → Secrets** and paste:

```toml
GOOGLE_API_KEY = "your_real_key"
```

8. Click **Deploy**

Your permanent link will look like:

**https://transtech-bill-desk.streamlit.app**

(Streamlit may add a random suffix if the name is taken.)

### 3. Use it every day

Open that Streamlit link → Upload bills → Process Bills → Download Excel.

## Files

- `app.py` — main website
- `customer_master.py` / `freight_master.py` — master lookups
- `invoice_history.py` — processed invoice store
- `excel_export.py` / `billing_statement.py` — Excel downloads
- `data/master_database.xlsx` — customer and freight master
- `requirements.txt` — Python packages

