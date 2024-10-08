import threading
import time
import argparse
import yaml
import register as register
from core.metadata_manager.metadata import MetadataManager
def parse_args():
    parser = argparse.ArgumentParser(
        description="Proxy to monitor supported bioreactors"
    )
    parser.add_argument(
        '--simulated', 
        type=str, 
        default=None, 
        help='Run in simulated mode and provide file to take data from.'
    )                                       
    parser.add_argument(
        '-s', '--seconds', 
        type=int, 
        default=None, 
        help='Number of seconds between changes (optional for Simulated mode).'
    )
    parser.add_argument(
        '-d', '--delay', 
        type=int, 
        default=None, 
        help='A delay in seconds before the proxy begins.'
    )
    return parser.parse_args()

def _get_output_module(config):
    outputs = config["OUTPUTS"]
    output_objects = {}
    fallback_codes = set()
    
    for out_data in outputs:
        output_code = out_data.pop("code")
        fallback_code = out_data.pop("fallback", None)
        if fallback_code:
            fallback_codes.add(fallback_code)
        output_objects[output_code] = {"data": out_data, 
                                       "fallback_code": fallback_code}
    
    for code, out_data in output_objects.items():
        fallback = None
        if out_data["fallback_code"]:
            fallback = output_objects[out_data["fallback_code"]].get("output")
        output_obj = register.get_output_adapter(code)(fallback=fallback,
                                                        **out_data["data"])
        output_objects[code]["output"] = output_obj
    
    for code, out_data in output_objects.items():
        if code not in fallback_codes:
            return out_data["output"]
    
    return None

def _get_existing_ids(output_module,metadata_manager):
    topic = metadata_manager.details()
    output_module.subscribe(topic)
    time.sleep(2)
    output_module.unsubscribe(topic)
    ids = []
    for k,v in output_module.messages.items():
        if metadata_manager.is_called(k,topic):
            ids.append(metadata_manager.get_instance_id(k))
    output_module.reset_messages()
    return ids
    
def _process_instance(instance, output):
    """Processes a single equipment instance."""
    equipment_data = instance["equipment"]
    equipment_code = equipment_data["code"]
    data = equipment_data["data"]
    requirements = equipment_data["requirements"]
    adapter = register.get_equipment_adapter(equipment_code)
    manager = MetadataManager()
    if data["instance_id"] in _get_existing_ids(output,manager):
        raise ValueError(f'ID: {data["instance_id"]} is taken.')

    try:
        equipment_adapter = adapter(data, output, **requirements)
    except ValueError as ex:
        print(f"Error processing instance {data['instance_id']}:")
        print(ex)
        return None
    
    return equipment_adapter

def _start_adapter_in_thread(adapter):
    """Run the adapter's start function in a separate thread."""
    thread = threading.Thread(target=adapter.start)
    thread.daemon = True
    thread.start()
    return thread

def main():
    with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)
    args = parse_args()
    delay = args.delay if args.delay is not None else 0
    output = _get_output_module(config)
    adapter_threads = []
    adapters = []

    for equipment_instance in config["EQUIPMENT_INSTANCES"]:
        adapter = _process_instance(equipment_instance, output)
        if adapter is None:
            continue

        adapters.append(adapter)
        equipment_id = equipment_instance["equipment"]["code"]
        instance_id = equipment_instance['equipment']['data']['instance_id']
        if args.simulated is not None:
            if not hasattr(adapter, "simulate"):
                raise NotImplementedError(f'Adapter {equipment_id} does not support simulation.')
            print(f"Simulator started for instance {instance_id}.")
            adapter.simulate(args.simulated, args.seconds, delay)
        else:
            print(f"Proxy started for instance {instance_id}.")
            thread = _start_adapter_in_thread(adapter)
            adapter_threads.append(thread)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down all adapters...")
        for adapter in adapters:
            try:
                adapter.stop()
                print(f"Adapter for {adapter} stopped successfully.")
            except Exception as e:
                print(f"Error stopping adapter: {e}")

if __name__ == "__main__":
    main()
