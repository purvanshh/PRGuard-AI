variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  type    = string
  default = "prguard-prod"
}

variable "kubernetes_version" {
  type    = string
  default = "1.30"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "private_subnets" {
  type    = list(string)
  default = ["10.42.1.0/24", "10.42.2.0/24", "10.42.3.0/24"]
}

variable "public_subnets" {
  type    = list(string)
  default = ["10.42.101.0/24", "10.42.102.0/24", "10.42.103.0/24"]
}

variable "worker_instance_type" {
  type    = string
  default = "m6i.large"
}

variable "postgres_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "postgres_username" {
  type    = string
  default = "prguard"
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.medium"
}
