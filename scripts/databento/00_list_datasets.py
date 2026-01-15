import databento as db
from mxm_secrets import get_secret

api_key = get_secret("mxm/dev/databento/api-key")

client = db.Historical(api_key)

datasets = client.metadata.list_datasets()

print(datasets)
