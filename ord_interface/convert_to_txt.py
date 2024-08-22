# import requirements
from ord_schema.message_helpers import load_message, write_message
from ord_schema.proto import dataset_pb2

# load the binary ord file
dataset = load_message("ord_dataset-89b083710e2d441aa0040c361d63359f.pb.gz", dataset_pb2.Dataset)
# save the ord file as human readable text
write_message(dataset, "ord_dataset-89b083710e2d441aa0040c361d63359f.pbtxt")
