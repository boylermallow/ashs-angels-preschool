# Ash's Angels Preschool App

A Streamlit preschool admin app for managing children, sessions, parent approvals, and parent notifications.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Private child, parent, login, and message data is intentionally kept out of GitHub.

## Admin login for deployment

When deploying on Streamlit, add these app secrets so the public app creates the admin account without putting the password in GitHub:

```toml
ASH_ADMIN_EMAIL = "your-admin-email@example.com"
ASH_ADMIN_PASSWORD = "your-secure-password"
```
