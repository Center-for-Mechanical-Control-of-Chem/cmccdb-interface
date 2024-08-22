# import requirements
from ord_schema.message_helpers import load_message, write_message
from ord_schema.proto import dataset_pb2

# load the binary ord file
dataset = load_message("Indole_synthesis.pbtxt", dataset_pb2.Dataset)
# save the ord file as human readable text
write_message(dataset, "ord_dataset-f388f8c73d6343189093770060fc3097.pb.gz")
