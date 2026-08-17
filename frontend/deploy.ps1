# Build the React frontend and publish it to the S3 bucket + CloudFront
# distribution that template.yaml creates. Run this after `sam build; sam
# deploy` -- SAM/CloudFormation manages the bucket and distribution
# themselves, but not what's inside the bucket. That's this script's job.
#
# PowerShell equivalent of deploy.sh, for running directly from Windows
# PowerShell without needing Git Bash/WSL.

$ErrorActionPreference = "Stop"

$StackName = "portfolio-monitor"

Set-Location -Path $PSScriptRoot

Write-Host "==> Building frontend"
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }

Write-Host "==> Looking up stack resources"
# Bucket and distribution have no dedicated stack Outputs (only the
# combined FrontendUrl does) -- their physical IDs come straight from the
# stack's resource list instead, same describe-stack-resources pattern
# docs/04-deploy.md already uses to find the state machine's ARN.
$BucketName = aws cloudformation describe-stack-resources `
  --stack-name $StackName `
  --logical-resource-id FrontendBucket `
  --query "StackResources[0].PhysicalResourceId" `
  --output text
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($BucketName) -or $BucketName -eq "None") {
  throw "Could not find the FrontendBucket stack resource. Has 'sam deploy' been run with the latest template.yaml?"
}

$DistributionId = aws cloudformation describe-stack-resources `
  --stack-name $StackName `
  --logical-resource-id FrontendDistribution `
  --query "StackResources[0].PhysicalResourceId" `
  --output text
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($DistributionId) -or $DistributionId -eq "None") {
  throw "Could not find the FrontendDistribution stack resource. Has 'sam deploy' been run with the latest template.yaml?"
}

Write-Host "==> Syncing dist/ to s3://$BucketName/"
aws s3 sync dist/ "s3://$BucketName/" --delete
if ($LASTEXITCODE -ne 0) { throw "aws s3 sync failed" }

Write-Host "==> Invalidating CloudFront cache ($DistributionId)"
aws cloudfront create-invalidation `
  --distribution-id $DistributionId `
  --paths "/*" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "aws cloudfront create-invalidation failed" }

$FrontendUrl = aws cloudformation describe-stacks `
  --stack-name $StackName `
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" `
  --output text

Write-Host "==> Done"
Write-Host "Frontend live at: $FrontendUrl"
Write-Host "(A brand-new distribution can take several minutes to finish propagating globally --"
Write-Host " if it 404s right after the first deploy, wait a bit and retry before assuming it's broken.)"
