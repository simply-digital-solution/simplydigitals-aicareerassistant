# Deployment Setup Guide

This document captures the one-time AWS infrastructure setup for AI Career Assistant.
Completed: June 2026

---

## Architecture

| Component | Service | URL |
|---|---|---|
| Frontend (React) | S3 + CloudFront | `aicareerassistant.simplydigitals.com.sg` |
| Backend (FastAPI) | EC2 + Nginx + Docker | `api.aicareerassistant.simplydigitals.com.sg` |
| Database | RDS PostgreSQL | Internal (not public) |
| Container Registry | ECR | `090960193288.dkr.ecr.ap-southeast-2.amazonaws.com/aicareerassistant-api` |

---

## AWS Resources Created

| Resource | Name / ID | Region |
|---|---|---|
| EC2 Instance | `ip-172-31-30-78` | `ap-southeast-2` |
| EC2 Elastic IP | `3.27.152.240` | `ap-southeast-2` |
| Security Group | `sg-0d4ab6be16f829fc9` | `ap-southeast-2` |
| ECR Repository | `aicareerassistant-api` | `ap-southeast-2` |
| S3 Bucket | `aicareerassistant-ui` | `ap-southeast-2` |
| CloudFront Distribution | `EBH9EUSUFNBAA` | Global |
| CloudFront Domain | `d2fe9fn9ie77qy.cloudfront.net` | Global |
| ACM Certificate (CloudFront) | `29ed505b-6e2f-4e9b-9f74-5679d768f424` | `us-east-1` (required for CloudFront) |
| ACM Certificate (API) | Let's Encrypt via Certbot | EC2 |

---

## Step 1 — ECR Repository

```bash
aws ecr create-repository \
  --repository-name aicareerassistant-api \
  --region ap-southeast-2
```

---

## Step 2 — ACM Certificate for CloudFront

> Must be in us-east-1 regardless of deployment region — CloudFront requirement.

```bash
aws acm request-certificate \
  --domain-name aicareerassistant.simplydigitals.com.sg \
  --validation-method DNS \
  --region us-east-1
```

Get the DNS validation record:

```bash
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:090960193288:certificate/29ed505b-6e2f-4e9b-9f74-5679d768f424 \
  --region us-east-1
```

Add this CNAME on your DNS provider:

| Field | Value |
|---|---|
| Type | CNAME |
| Name | `_4286278c4ee7ab16a8bba9577fb9e932.aicareerassistant` |
| Value | `_6dc9a16b73ed215bc10fd82174368fe9.jkddzztszm.acm-validations.aws.` |
| TTL | 300 |

Check validation status (wait for `"ISSUED"`):

```bash
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:090960193288:certificate/29ed505b-6e2f-4e9b-9f74-5679d768f424 \
  --region us-east-1 \
  --query "Certificate.Status"
```

---

## Step 3 — CloudFront Distribution

```bash
cat > /tmp/cf-config.json << 'EOF'
{
  "CallerReference": "aicareerassistant-2026",
  "Aliases": {
    "Quantity": 1,
    "Items": ["aicareerassistant.simplydigitals.com.sg"]
  },
  "DefaultRootObject": "index.html",
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "aicareerassistant-ui-s3",
      "DomainName": "aicareerassistant-ui.s3.ap-southeast-2.amazonaws.com",
      "S3OriginConfig": {
        "OriginAccessIdentity": ""
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "aicareerassistant-ui-s3",
    "ViewerProtocolPolicy": "redirect-to-https",
    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"]
    },
    "Compress": true
  },
  "CustomErrorResponses": {
    "Quantity": 2,
    "Items": [
      {
        "ErrorCode": 403,
        "ResponsePagePath": "/index.html",
        "ResponseCode": "200",
        "ErrorCachingMinTTL": 0
      },
      {
        "ErrorCode": 404,
        "ResponsePagePath": "/index.html",
        "ResponseCode": "200",
        "ErrorCachingMinTTL": 0
      }
    ]
  },
  "ViewerCertificate": {
    "ACMCertificateArn": "arn:aws:acm:us-east-1:090960193288:certificate/29ed505b-6e2f-4e9b-9f74-5679d768f424",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021"
  },
  "Enabled": true,
  "Comment": "AI Career Assistant UI"
}
EOF

aws cloudfront create-distribution \
  --distribution-config file:///tmp/cf-config.json
```

---

## Step 4 — S3 Bucket Policy (allow CloudFront only)

```bash
cat > /tmp/s3-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::aicareerassistant-ui/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::090960193288:distribution/EBH9EUSUFNBAA"
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-policy \
  --bucket aicareerassistant-ui \
  --policy file:///tmp/s3-policy.json \
  --region ap-southeast-2
```

---

## Step 5 — DNS Records

Add these on your DNS provider:

| Type | Name | Value | TTL | Purpose |
|---|---|---|---|---|
| CNAME | `aicareerassistant` | `d2fe9fn9ie77qy.cloudfront.net` | 300 | Frontend via CloudFront |
| A | `api.aicareerassistant` | `3.27.152.240` | 300 | Backend API on EC2 |
| CNAME | `_4286278c4ee7ab16a8bba9577fb9e932.aicareerassistant` | `_6dc9a16b73ed215bc10fd82174368fe9.jkddzztszm.acm-validations.aws.` | 300 | ACM cert validation |

---

## Step 6 — EC2 Security Group Rules

```bash
# SSH — your IP only (replace with your actual IP)
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d4ab6be16f829fc9 \
  --protocol tcp --port 22 \
  --cidr <YOUR_IP>/32 \
  --region ap-southeast-2

# HTTP — public
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d4ab6be16f829fc9 \
  --protocol tcp --port 80 \
  --cidr 0.0.0.0/0 \
  --region ap-southeast-2

# HTTPS — public
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d4ab6be16f829fc9 \
  --protocol tcp --port 443 \
  --cidr 0.0.0.0/0 \
  --region ap-southeast-2
```

---

## Step 7 — EC2 Server Setup

SSH into EC2:

```bash
ssh -i ~/.ssh/aicareerassistant.pem ubuntu@3.27.152.240
```

Install Docker, Docker Compose, AWS CLI, Nginx, Certbot:

```bash
# Docker
sudo apt update && sudo apt install -y docker.io docker-compose

# Add ubuntu user to docker group
sudo usermod -aG docker ubuntu && newgrp docker

# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt install -y unzip
unzip awscliv2.zip
sudo ./aws/install

# Nginx + Certbot
sudo apt install -y nginx certbot python3-certbot-nginx

# Configure AWS credentials
aws configure
# Enter: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, ap-southeast-2, json

# Verify ECR login
aws ecr get-login-password --region ap-southeast-2 | \
  docker login --username AWS --password-stdin \
  090960193288.dkr.ecr.ap-southeast-2.amazonaws.com

# Create app directory
mkdir -p /home/ubuntu/app
```

---

## Step 8 — SSL Certificate for API (Let's Encrypt)

```bash
sudo certbot --nginx -d api.aicareerassistant.simplydigitals.com.sg
```

Certificate auto-renews via systemd timer installed by Certbot.

---

## Step 9 — Nginx Config

Edit `/etc/nginx/sites-available/default`:

```nginx
upstream api {
    server unix:/home/ubuntu/app/socket/app.sock;
}

server {
    listen 80;
    server_name api.aicareerassistant.simplydigitals.com.sg;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name api.aicareerassistant.simplydigitals.com.sg;

    ssl_certificate     /etc/letsencrypt/live/api.aicareerassistant.simplydigitals.com.sg/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.aicareerassistant.simplydigitals.com.sg/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /api/ {
        proxy_pass         http://api;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /health {
        proxy_pass http://api;
    }

    location / {
        return 404;
    }
}
```

Test and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Step 10 — GitHub Secrets

### Organisation Secrets (`simply-digital-solution`)
| Secret | Value |
|---|---|
| `AWS_ACCOUNT_ID` | `090960193288` |
| `AWS_REGION` | `ap-southeast-2` |
| `AWS_ACCESS_KEY_ID` | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key |

### Repository Secrets (`simplydigitals-aicareerassistant`)
| Secret | Value |
|---|---|
| `ECR_REGISTRY` | `090960193288.dkr.ecr.ap-southeast-2.amazonaws.com` |
| `ECR_REPOSITORY` | `aicareerassistant-api` |
| `S3_BUCKET` | `aicareerassistant-ui` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `EBH9EUSUFNBAA` |
| `EC2_HOST` | `3.27.152.240` |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | Contents of `aicareerassistant.pem` |
| `PROD_API_URL` | `https://api.aicareerassistant.simplydigitals.com.sg` |
| `DATABASE_URL` | RDS PostgreSQL connection string |
| `JWT_SECRET_KEY` | Random secret (`openssl rand -hex 32`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `HCAPTCHA_SECRET_KEY` | hCaptcha secret key |
| `VITE_HCAPTCHA_SITE_KEY` | hCaptcha site key |

---

## Deploying a New Version

Everything after this point is **fully automated**. Just push to `main`:

```bash
git push origin main
```

GitHub Actions will:
1. Run tests and lint
2. Build Docker image → push to ECR
3. Copy `docker-compose.prod.yml` and `nginx/` to EC2
4. Write `.env` file on EC2 from GitHub Secrets
5. Pull new image and restart containers
6. Run database migrations (if changed)
7. Health check `https://api.aicareerassistant.simplydigitals.com.sg/health`
8. Build React UI → sync to S3 → invalidate CloudFront cache

---

## Useful Commands

### Check running containers on EC2
```bash
ssh -i ~/.ssh/aicareerassistant.pem ubuntu@3.27.152.240
docker ps
```

### View API logs
```bash
docker compose -f /home/ubuntu/app/docker-compose.prod.yml logs -f api
```

### Manually trigger ECR login on EC2
```bash
aws ecr get-login-password --region ap-southeast-2 | \
  docker login --username AWS --password-stdin \
  090960193288.dkr.ecr.ap-southeast-2.amazonaws.com
```

### Check nginx status
```bash
sudo systemctl status nginx
sudo nginx -t
```

### Renew SSL certificate manually
```bash
sudo certbot renew --dry-run
```

### Check CloudFront distribution status
```bash
aws cloudfront get-distribution \
  --id EBH9EUSUFNBAA \
  --query "Distribution.Status"
```
