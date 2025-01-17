import logging
import os
import resource
import time

import numpy as np
import seml
import torch
from sacred import Experiment

from data.customed_dataset import MYDataset
from data.data_preparation import load_data, graph_preprocess
from models.get_model import get_model
from train.trainer import Trainer

ex = Experiment()
seml.setup_logger(ex)


@ex.post_run_hook
def collect_stats(_run):
    seml.collect_exp_stats(_run)


@ex.config
def config():
    overwrite = None
    db_collection = None
    if db_collection is not None:
        ex.observers.append(seml.create_mongodb_observer(db_collection, overwrite=overwrite))


@ex.automain
def run(dataset_name,
        graphmodel,
        num_batches,
        hidden_channels,
        num_layers,
        heads=None):
    

    logging.info(
        f'dataset: {dataset_name}, graphmodel: {graphmodel}, '
        f'num_batches: {num_batches}')

    device = 'cuda' if torch.cuda.is_available else 'cpu'

    # common preprocess
    start_time = time.time()
    graph, (_, val_indices, test_indices) = load_data(dataset_name, 1)
    logging.info("Graph loaded!\n")
    disk_loading_time = time.time() - start_time

    start_time = time.time()
    graph_preprocess(graph)
    logging.info("Graph processed!\n")
    graph_preprocess_time = time.time() - start_time

    trainer = Trainer('part',
                      'batch_ppr',
                      num_batches, 
                      micro_batch=1,
                      batch_size=1,
                      epoch_max=0,
                      epoch_min=1,
                      patience=1)

    # common preprocess
    start_time = time.time()
    dataset = MYDataset(graph.x.cpu().detach().numpy(),
                        graph.y.cpu().detach().numpy(),
                        graph.adj_t.to_scipy('csr'),
                        train_loader=None,
                        val_loader=[None, None, None],
                        test_loader=[None, None, None],
                        batch_order={'ordered': False, 'sampled': False},
                        cache_sub_adj=True,
                        cache_origin_adj=False,
                        cache=True)
    caching_time = time.time() - start_time

    model = get_model(graphmodel,
                      graph.num_node_features,
                      graph.y.max().item() + 1,
                      hidden_channels,
                      num_layers,
                      heads,
                      device)

    for _file in os.listdir(f'./pretrained/{graphmodel}_{dataset_name}/'):
        no = _file.split('.')[0].split('_')[1]
        trainer.inference(dataset=dataset,
                          model=model,
                          val_nodes=val_indices,
                          test_nodes=test_indices,
                          adj=graph.adj_t,
                          x=graph.x,
                          y=graph.y,
                          file_dir='./pretrained',
                          comment=f'{graphmodel}_{dataset_name}',
                          run_no=no, 
                          full_infer=True, 
                          record_numbatch=False)
        

    results = {
        'disk_loading_time': disk_loading_time,
        'graph_preprocess_time': graph_preprocess_time,
        'caching_time': caching_time,
        'gpu_memory': torch.cuda.max_memory_allocated(),
        'max_memory': 1024 * resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    }

    for key, item in trainer.database.items():
        if key != 'training_curves':
            results[f'{key}_record'] = item
            item = np.array(item)
            results[f'{key}_stats'] = (item.mean(), item.std(),) if len(item) else (0., 0.,)

    return results
