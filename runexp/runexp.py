import logging
import multiprocessing
import os
import copy
import sys
import json
import pickle
from tqdm.auto import tqdm

from .utils import dict_subset, unravel_dict, can_stringify, CONFIG

from os.path import dirname, abspath, join
from os import listdir

from .messages import *
from .utils import dirlock

class Runner:

    def __init__(self, func, output, printlog=True, log_level=logging.INFO):

        try:
            os.mkdir(output)
        except FileExistsError:
            answer = input(OUTPUT_DIR_EXISTS.format(output))
            if answer == "y":
                pass
            else:
                exit(1)

        self.func = func
        self.output_dir = output
        self.digits = 6
        global dirlock
        dirlock = multiprocessing.Lock()

        if printlog is True:
            logging.basicConfig(level=log_level,
                                format="%(asctime)s [%(levelname)s] %(message)s",
                                handlers=[logging.StreamHandler(sys.stdout)])
        else:
            raise NotImplementedError("Logging to file not yet implemented")


    #####################################################
    #        Methods that should be overwritten         #
    #####################################################

    def make_kwargs(self, config):
        raise NotImplementedError(f"Implement `make_kwargs` for type {self}")

    def description(self, config) -> str:
        return f"Implement `description(config)` for {type(self)} to get informative progress"

    #####################################################
    #                   Main dispatch                   #
    #####################################################

    def run_one(self, config):
        self.run_experiment(config)

    def run_batch(self, config, parallel=False, num_workers=None):

        configs = unravel_dict(config)
        total_exp = len(configs)

        print("Filtering experiments based on disk")
        configs = self.filter_experiments(configs)
        print(f"Skipping {total_exp - len(configs)} experiments")
        self.n_experiments = len(configs)
        print(f"Running {len(configs)} remaining experiments")

        if parallel is True:
            if num_workers is None:
                num_workers = multiprocessing.cpu_count() - 1

            print(f"Running in parallel with {num_workers} threads")

            manager = multiprocessing.Manager()
            dirlock = manager.Lock()

            pool = multiprocessing.Pool(num_workers, maxtasksperchild=1, initargs=(dirlock,))
            lst = list(tqdm(pool.imap(self.run_experiment, configs), total=len(configs)))

        else:
            pbar = tqdm(total=len(configs))
            for config in configs:
                pbar.set_description(self.description(config))
                self.run_experiment(config)
                pbar.update()

    def run_experiment(self, config):
        dirname = self.mkdir()
        kwargs = self.make_kwargs(config)
        result = self.func(**kwargs)
        self.save_result(config, result, dirname)

    #####################################################
    #                   Helper functions                #
    #####################################################

    def remove_empty_subdirs(self):
        for edir in listdir(self.output_dir):
            full_dir = join(self.output_dir, edir)
            if len(listdir(full_dir)) == 0:
                os.rmdir(full_dir)

        return True

    def filter_experiments(self, configs):
        """
            Filter experiments already finished in output directory
        """
        filtered = copy.copy(configs)
        for edir in listdir(self.output_dir):
            full_dir = join(self.output_dir, edir)

            if CONFIG not in listdir(full_dir):
                if len(listdir(full_dir)) != 0:
                    raise ValueError("{full_dir} is not emptpy, but does not contain {CONFIG}, was the directory created by RunExp?")
                else:
                    continue
            with open(join(self.output_dir, edir, CONFIG), "r") as f:
                disk_conf = json.loads(f.read())
                if disk_conf in filtered:
                    filtered.remove(disk_conf)

        return filtered


    def mkdir(self):
        global dirlock
        with dirlock:
            idx = self.next_emtpy_index()
            # make dir for results
            dirname = (self.digits - len(str(idx))) * "0" + str(idx)
            full_dir = join(self.output_dir, dirname)
            try:
                os.mkdir(full_dir)
            except FileExistsError:
                assert len(listdir(full_dir)) == 0, f"{full_dir} should be empty"
                pass
            return full_dir

    def next_emtpy_index(self):
        """
            RunExp creates output directories with numeric names.
            This function finds the next directory name
        """
        last_idx = 0
        for edir in sorted(listdir(self.output_dir)):
            idx = int(edir)
            if idx - 1 != last_idx:  # some missing number in the chain
                return last_idx + 1
            # if len(listdir(join(self.output_dir, edir))) == 0:  # found empty dir
            #     return idx
            last_idx = idx
        return last_idx + 1


    def save_result(self, config, result, dirname):

        with open(join(dirname, CONFIG), "w") as f:
            f.write(json.dumps(config))

        for key, value in result.items():
            if "." in str(key): # will assume extension is given
                with open(join(dirname, str(key)), "w") as f:
                    f.write(str(value))

            elif can_stringify(value):
                with open(join(dirname, str(key) + ".txt"), "w") as f:
                    f.write(str(value))

            elif isinstance(value, dict):
                with open(join(dirname, str(key) + ".json"), "w") as f:
                    f.write(json.dumps(value))

            elif isinstance(value, list) and all(can_stringify(v) for v in value):
                with open(join(dirname, str(key) + ".txt"), "w"):
                    f.write("\n".join(value))
            else:  # save as pickle
                with open(join(dirname, str(key) + ".pickle"), "wb") as f:
                    pickle.dump(value, f)
