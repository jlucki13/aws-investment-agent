#!/usr/bin/env bash
# Build the React frontend and publish it to the S3 bucket + CloudFront
# distribution that template.yaml creates. Run this after `sam build && sam
# deploy` -- SAM/CloudFormation manages the bucket and distribution
# themselves, but not what's inside the bucket. That's this script's job.
#
# Bash on purpose, not because Windows is unsupported: bash also runs fine
# under Git Bash or WSL on Windows. See deploy.ps1 for a native PowerShell
# equivalent.
set -euo pipefail

STACK_NAME="portfolio-monitor"

cd "$(dirname "$0")"

echo "==> Building frontend"
npm run build

echo "==> Looking up stack resources"
# Bucket and distribution have no dedicated stack Outputs (only the
# combined FrontendUrl does) -- their physical IDs come straight from the
# stack's resource list instead, same describe-stack-resources pattern
# docs/04-deploy.md already uses to find the state machine's ARN.
BUCKET_NAME=$(aws cloudformation describe-stack-resources \
  --stack-name "$STACK_NAME" \
  --logical-resource-id FrontendBucket \
  --query "StackResources[0].PhysicalResourceId" \
  --output text)

DISTRIBUTION_ID=$(aws cloudformation describe-stack-resources \
  --stack-name "$STACK_NAME" \
  --logical-resource-id FrontendDistribution \
  --query "StackResources[0].PhysicalResourceId" \
  --output text)

if [[ -z "$BUCKET_NAME" || "$BUCKET_NAME" == "None" ]]; then
  echo "Could not find the FrontendBucket stack resource. Has 'sam deploy' been run with the latest template.yaml?" >&2
  exit 1
fi

if [[ -z "$DISTRIBUTION_ID" || "$DISTRIBUTION_ID" == "None" ]]; then
  echo "Could not find the FrontendDistribution stack resource. Has 'sam deploy' been run with the latest template.yaml?" >&2
  exit 1
fi

echo "==> Syncing dist/ to s3://$BUCKET_NAME/"
aws s3 sync dist/ "s3://$BUCKET_NAME/" --delete

echo "==> Invalidating CloudFront cache ($DISTRIBUTION_ID)"
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" > /dev/null

FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" \
  --output text)

echo "==> Done"
echo "Frontend live at: $FRONTEND_URL"
echo "(A brand-new distribution can take several minutes to finish propagating globally --"
echo " if it 404s right after the first deploy, wait a bit and retry before assuming it's broken.)"
