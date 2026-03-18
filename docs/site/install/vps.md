# Розгортання на VPS

## Terraform (рекомендовано)

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars
# Заповніть terraform.tfvars
terraform init
terraform apply
```

## Ручне встановлення

### 1. Підключитись до сервера

```bash
ssh root@your-server-ip
```

### 2. Встановити залежності

```bash
apt update && apt upgrade -y
apt install python3.12 python3.12-venv nginx certbot
```

### 3. Створити користувача

```bash
useradd -m -s /bin/bash posipaka
```

### 4. Встановити Posipaka

```bash
su - posipaka
pip install posipaka[all]
posipaka setup
```

### 5. Systemd сервіс

```bash
sudo cp deploy/posipaka.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable posipaka
sudo systemctl start posipaka
```

### 6. Nginx reverse proxy

```bash
sudo cp deploy/nginx/posipaka.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/posipaka.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7. SSL сертифікат

```bash
sudo certbot --nginx -d your-domain.com
```

## Blue-Green Deploy

```bash
bash scripts/blue_green_deploy.sh
```

Автоматичний rollback при невдалому health check.
