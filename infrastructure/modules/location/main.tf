# OpenLEWS Amazon Location Service Module
# This is used to reverse-geocode lat/lon using a geocoder

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment (dev, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}


resource "aws_location_place_index" "this" {
  index_name  = "${var.project_name}-${var.environment}-place-index"
  data_source = "Here"

  tags = merge(var.tags, {
    Component = "Location"
  })
}

output "place_index_name" {
  value = aws_location_place_index.this.index_name
}

output "place_index_arn" {
  value = aws_location_place_index.this.index_arn
}
