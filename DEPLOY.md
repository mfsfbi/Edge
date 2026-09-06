# INTEX — deployment note

This build is the public pharmaceutical/formulation edition of the INTEX site.

## Local

```bash
pip install -r requirements.txt
python app.py
```

## Render

Start command:

```bash
gunicorn app:app
```

The site uses SQLite for the bundled operational demo and can be extended with the production database of choice.
