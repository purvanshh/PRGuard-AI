# PRGuard AI Terraform Module

This module is a production-oriented starting point for AWS infrastructure: VPC, EKS, RDS PostgreSQL, and ElastiCache Redis. It intentionally exposes inputs for CIDRs, node sizes, and secret wiring so teams can adapt it to their account standards.

```bash
terraform init
terraform plan -var='cluster_name=prguard-prod'
terraform apply
```
