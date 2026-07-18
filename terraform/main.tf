terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = var.private_subnets
  public_subnets  = var.public_subnets

  enable_nat_gateway = true
  single_nat_gateway = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version
  subnet_ids      = module.vpc.private_subnets
  vpc_id          = module.vpc.vpc_id

  eks_managed_node_groups = {
    workers = {
      min_size     = 2
      max_size     = 10
      desired_size = 3
      instance_types = [var.worker_instance_type]
    }
  }
}

resource "aws_db_subnet_group" "prguard" {
  name       = "${var.cluster_name}-db"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.cluster_name}-postgres"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.postgres_instance_class
  allocated_storage      = 50
  db_name                = "prguard"
  username               = var.postgres_username
  password               = var.postgres_password
  db_subnet_group_name   = aws_db_subnet_group.prguard.name
  skip_final_snapshot    = false
  publicly_accessible    = false
  storage_encrypted      = true
}

resource "aws_elasticache_subnet_group" "prguard" {
  name       = "${var.cluster_name}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.cluster_name}-redis"
  description                = "PRGuard Redis broker/cache"
  engine                     = "redis"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.prguard.name
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}
