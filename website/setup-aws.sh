#!/usr/bin/env bash
# One-time AWS setup for simplydigitals.com.sg static website hosting.
# Run this locally with AWS credentials that have S3, CloudFront, and ACM access.
#
# After this script completes you must:
#   1. Add the ACM DNS validation CNAME record at ReadySpace (printed below)
#   2. Wait for the cert to become ISSUED (~2 min after DNS validates)
#   3. Re-run step 3 below (or run the full script again — it is idempotent)
#   4. Add the CloudFront CNAME at ReadySpace pointing simplydigitals.com.sg → CloudFront domain
#   5. Add two GitHub secrets: WEBSITE_S3_BUCKET and WEBSITE_CLOUDFRONT_DISTRIBUTION_ID

set -euo pipefail

DOMAIN="simplydigitals.com.sg"
WWW_DOMAIN="www.simplydigitals.com.sg"
BUCKET="simplydigitals.com.sg"
APP_REGION="ap-southeast-1"   # bucket region (same as EC2)
ACM_REGION="us-east-1"        # CloudFront requires certs in us-east-1

echo "=== Step 1: Create S3 bucket ==="
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Bucket $BUCKET already exists — skipping"
else
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$APP_REGION" \
    --create-bucket-configuration LocationConstraint="$APP_REGION"
  echo "Created bucket: $BUCKET"
fi

# Block public access (CloudFront will access via OAC, not public URLs)
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo ""
echo "=== Step 2: Request ACM certificate (us-east-1) ==="
CERT_ARN=$(aws acm list-certificates \
  --region "$ACM_REGION" \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn | [0]" \
  --output text 2>/dev/null)

if [ "$CERT_ARN" = "None" ] || [ -z "$CERT_ARN" ]; then
  CERT_ARN=$(aws acm request-certificate \
    --region "$ACM_REGION" \
    --domain-name "$DOMAIN" \
    --subject-alternative-names "$WWW_DOMAIN" \
    --validation-method DNS \
    --query CertificateArn \
    --output text)
  echo "Requested cert: $CERT_ARN"
else
  echo "Certificate already exists: $CERT_ARN"
fi

echo ""
echo "=== DNS validation records — add these at ReadySpace ==="
aws acm describe-certificate \
  --region "$ACM_REGION" \
  --certificate-arn "$CERT_ARN" \
  --query 'Certificate.DomainValidationOptions[*].{Domain:DomainName,Name:ResourceRecord.Name,Value:ResourceRecord.Value}' \
  --output table

CERT_STATUS=$(aws acm describe-certificate \
  --region "$ACM_REGION" \
  --certificate-arn "$CERT_ARN" \
  --query 'Certificate.Status' \
  --output text)

echo ""
echo "Certificate status: $CERT_STATUS"
if [ "$CERT_STATUS" != "ISSUED" ]; then
  echo ""
  echo "⚠️  Certificate not yet issued. Add the DNS CNAME records above at ReadySpace,"
  echo "    wait ~2 minutes for validation, then re-run this script."
  exit 0
fi

echo ""
echo "=== Step 3: Create CloudFront Origin Access Control ==="
OAC_ID=$(aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='$DOMAIN-oac'].Id | [0]" \
  --output text 2>/dev/null)

if [ "$OAC_ID" = "None" ] || [ -z "$OAC_ID" ]; then
  OAC_ID=$(aws cloudfront create-origin-access-control \
    --origin-access-control-config \
      "Name=${DOMAIN}-oac,Description=OAC for ${DOMAIN},SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
    --query 'OriginAccessControl.Id' \
    --output text)
  echo "Created OAC: $OAC_ID"
else
  echo "OAC already exists: $OAC_ID"
fi

echo ""
echo "=== Step 4: Create CloudFront distribution ==="
DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[?@=='$DOMAIN']].Id | [0]" \
  --output text 2>/dev/null)

if [ "$DIST_ID" = "None" ] || [ -z "$DIST_ID" ]; then
  BUCKET_REGIONAL_DOMAIN="${BUCKET}.s3.${APP_REGION}.amazonaws.com"
  DIST_JSON=$(aws cloudfront create-distribution --distribution-config "{
    \"CallerReference\": \"${DOMAIN}-$(date +%s)\",
    \"Comment\": \"${DOMAIN} company website\",
    \"DefaultRootObject\": \"index.html\",
    \"Aliases\": {
      \"Quantity\": 2,
      \"Items\": [\"${DOMAIN}\", \"${WWW_DOMAIN}\"]
    },
    \"Origins\": {
      \"Quantity\": 1,
      \"Items\": [{
        \"Id\": \"s3-${BUCKET}\",
        \"DomainName\": \"${BUCKET_REGIONAL_DOMAIN}\",
        \"S3OriginConfig\": {\"OriginAccessIdentity\": \"\"},
        \"OriginAccessControlId\": \"${OAC_ID}\"
      }]
    },
    \"DefaultCacheBehavior\": {
      \"TargetOriginId\": \"s3-${BUCKET}\",
      \"ViewerProtocolPolicy\": \"redirect-to-https\",
      \"CachePolicyId\": \"658327ea-f89d-4fab-a63d-7e88639e58f6\",
      \"Compress\": true,
      \"AllowedMethods\": {
        \"Quantity\": 2,
        \"Items\": [\"GET\", \"HEAD\"]
      }
    },
    \"CustomErrorResponses\": {
      \"Quantity\": 1,
      \"Items\": [{
        \"ErrorCode\": 403,
        \"ResponsePagePath\": \"/index.html\",
        \"ResponseCode\": \"200\",
        \"ErrorCachingMinTTL\": 0
      }]
    },
    \"PriceClass\": \"PriceClass_All\",
    \"Enabled\": true,
    \"HttpVersion\": \"http2and3\",
    \"ViewerCertificate\": {
      \"ACMCertificateArn\": \"${CERT_ARN}\",
      \"SSLSupportMethod\": \"sni-only\",
      \"MinimumProtocolVersion\": \"TLSv1.2_2021\"
    }
  }")

  DIST_ID=$(echo "$DIST_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['Id'])")
  DIST_DOMAIN=$(echo "$DIST_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['DomainName'])")
  echo "Created CloudFront distribution: $DIST_ID"
else
  DIST_DOMAIN=$(aws cloudfront get-distribution \
    --id "$DIST_ID" \
    --query 'Distribution.DomainName' \
    --output text)
  echo "CloudFront distribution already exists: $DIST_ID"
fi

echo ""
echo "=== Step 5: Attach S3 bucket policy for CloudFront OAC ==="
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{
    \"Sid\": \"AllowCloudFrontOAC\",
    \"Effect\": \"Allow\",
    \"Principal\": {\"Service\": \"cloudfront.amazonaws.com\"},
    \"Action\": \"s3:GetObject\",
    \"Resource\": \"arn:aws:s3:::${BUCKET}/*\",
    \"Condition\": {
      \"StringEquals\": {
        \"AWS:SourceArn\": \"arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${DIST_ID}\"
      }
    }
  }]
}"
echo "Bucket policy attached"

echo ""
echo "=== Step 6: Upload website files ==="
aws s3 sync "$(dirname "$0")/" "s3://${BUCKET}/" \
  --exclude "setup-aws.sh" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --delete
echo "Website files uploaded"

echo ""
echo "========================================"
echo "DONE. Next steps:"
echo ""
echo "1. Add these DNS records at ReadySpace (readyspace.com):"
echo "   CNAME  simplydigitals.com.sg     →  ${DIST_DOMAIN}"
echo "   CNAME  www.simplydigitals.com.sg →  ${DIST_DOMAIN}"
echo "   (or ALIAS/ANAME if ReadySpace supports it for the apex domain)"
echo ""
echo "2. Add these GitHub repository secrets:"
echo "   WEBSITE_S3_BUCKET                = ${BUCKET}"
echo "   WEBSITE_CLOUDFRONT_DISTRIBUTION_ID = ${DIST_ID}"
echo "========================================"
