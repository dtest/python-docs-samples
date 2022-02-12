# Copyright 2021 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import shlex
import subprocess
import time

from google.cloud.storage.bucket import Bucket

from google.cloud import storage
from google.cloud.retail import GcsSource, ImportErrorsConfig, \
    ImportProductsRequest, ProductInputConfig
from google.cloud.retail_v2 import ProductServiceClient

project_number = os.environ["GOOGLE_CLOUD_PROJECT_NUMBER"]
products_bucket_name = os.environ['BUCKET_NAME']
events_bucket_name = os.environ['EVENTS_BUCKET_NAME']
project_id = os.environ["GOOGLE_CLOUD_PROJECT_ID"]

product_resource_file = "../resources/products.json"
events_source_file = "../resources/user_events.json"

product_dataset = "products"
product_table = "products"
product_schema = "../resources/product_schema.json"
events_dataset = "user_events"
events_table = "events"
events_schema = "../resources/events_schema.json"

object_name = re.search('resources/(.*?)$', product_resource_file).group(1)
default_catalog = "projects/{0}/locations/global/catalogs/default_catalog/branches/default_branch".format(
    project_number)

storage_client = storage.Client()

def create_bucket(bucket_name: str) -> Bucket:
    """Create a new bucket in Cloud Storage"""
    print("Creating new bucket:" + bucket_name)
    bucket_exists = check_if_bucket_exists(bucket_name)
    if bucket_exists:
        print("Bucket {} already exists".format(bucket_name))
        return storage_client.bucket(bucket_name)
    else:
        bucket = storage_client.bucket(bucket_name)
        bucket.storage_class = "STANDARD"
        new_bucket = storage_client.create_bucket(bucket, location="us")
        print(
            "Created bucket {} in {} with storage class {}".format(
                new_bucket.name, new_bucket.location, new_bucket.storage_class
            )
        )
        return new_bucket


def check_if_bucket_exists(new_bucket_name):
    """Check if bucket is already exists"""
    bucket_exists = False
    buckets = storage_client.list_buckets()
    for bucket in buckets:
        if bucket.name == new_bucket_name:
            bucket_exists = True
            break
    return bucket_exists


def upload_data_to_bucket(bucket: Bucket):
    """Upload data to a GCS bucket"""
    blob = bucket.blob(object_name)
    blob.upload_from_filename(product_resource_file)
    print("Data from {} has being uploaded to {}".format(product_resource_file,
                                                         bucket.name))


def get_import_products_gcs_request():
    """Get import products from gcs request"""
    gcs_bucket = "gs://{}".format(products_bucket_name)
    gcs_errors_bucket = "{}/error".format(gcs_bucket)

    gcs_source = GcsSource()
    gcs_source.input_uris = ["{0}/{1}".format(gcs_bucket, object_name)]

    input_config = ProductInputConfig()
    input_config.gcs_source = gcs_source

    errors_config = ImportErrorsConfig()
    errors_config.gcs_prefix = gcs_errors_bucket

    import_request = ImportProductsRequest()
    import_request.parent = default_catalog
    import_request.reconciliation_mode = ImportProductsRequest.ReconciliationMode.INCREMENTAL
    import_request.input_config = input_config
    import_request.errors_config = errors_config

    print("---import products from google cloud source request---")
    print(import_request)

    return import_request


def import_products_from_gcs():
    """Call the Retail API to import products"""
    import_gcs_request = get_import_products_gcs_request()
    gcs_operation = ProductServiceClient().import_products(
        import_gcs_request)
    print(
        "Import operation is started: {}".format(gcs_operation.operation.name))

    while not gcs_operation.done():
        print("Please wait till operation is completed")
        time.sleep(5)
    print("Import products operation is completed")

    if gcs_operation.metadata is not None:
        print("Number of successfully imported products")
        print(gcs_operation.metadata.success_count)
        print("Number of failures during the importing")
        print(gcs_operation.metadata.failure_count)
    else:
        print("Operation.metadata is empty")

    print(
        "Wait 2 -5 minutes till products become indexed in the catalog,\
after that they will be available for search")

def create_bq_dataset(dataset_name):
    """Create a BigQuery dataset"""
    print("Creating dataset {}".format(dataset_name))
    if dataset_name not in list_bq_datasets():
        create_dataset_command = 'bq --location=US mk -d --default_table_expiration 3600 --description "This is my dataset." {}:{}'.format(
            project_id, dataset_name)
        output = subprocess.check_output(shlex.split(create_dataset_command))
        print(output)
        print("dataset is created")
    else:
        print("dataset {} already exists".format(dataset_name))


def list_bq_datasets():
    """List BigQuery datasets in the project"""
    list_dataset_command = "bq ls --project_id {}".format(project_id)
    list_output = subprocess.check_output(shlex.split(list_dataset_command))
    datasets = re.split(r'\W+', str(list_output))
    return datasets


def create_bq_table(dataset, table_name, schema):
    """Create a BigQuery table"""
    print("Creating BigQuery table {}".format(table_name))
    if table_name not in list_bq_tables(dataset):
        create_table_command = "bq mk --table {}:{}.{} {}".format(
            project_id,
            dataset,
            table_name, schema)
        output = subprocess.check_output(shlex.split(create_table_command))
        print(output)
        print("table is created")
    else:
        print("table {} already exists".format(table_name))


def list_bq_tables(dataset):
    """List BigQuery tables in the dataset"""
    list_tables_command = "bq ls {}:{}".format(project_id, dataset)
    tables = subprocess.check_output(shlex.split(list_tables_command))
    return str(tables)


def upload_data_to_bq_table(dataset, table_name, source, schema):
    """Upload data to the table from specified source file"""
    print("Uploading data form {} to the table {}.{}".format(source, dataset,
                                                             table_name))
    upload_data_command = "bq load --source_format=NEWLINE_DELIMITED_JSON {}:{}.{} {} {}".format(
        project_id, dataset, table_name, source, schema)
    output = subprocess.check_output(shlex.split(upload_data_command))
    print(output)


# Create a GCS bucket with products.json file
created_products_bucket = create_bucket(products_bucket_name)
upload_data_to_bucket(created_products_bucket)

# Create a GCS bucket with user_events.json file
created_events_bucket = create_bucket(events_bucket_name)
upload_data_to_bucket(created_events_bucket)

# Import prodcuts from the GCS bucket to the Retail catalog
import_products_from_gcs()

# Create a BigQuery table with products
create_bq_dataset(product_dataset)
create_bq_table(product_dataset, product_table, product_schema)
upload_data_to_bq_table(product_dataset, product_table,
                        product_resource_file, product_schema)

# Create a BigQuery table with user events
create_bq_dataset(events_dataset)
create_bq_table(events_dataset, events_table, events_schema)
upload_data_to_bq_table(events_dataset, events_table, events_source_file,
                        events_schema)