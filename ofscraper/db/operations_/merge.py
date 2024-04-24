import logging
import pathlib
import traceback

import ofscraper.utils.paths.paths as paths
from ofscraper.db.operations import (
    create_tables,
    get_single_model_via_profile,
    modify_tables,
)
from ofscraper.db.operations_.labels import (
    get_all_labels_transition,
    write_labels_table_transition,
)
from ofscraper.db.operations_.media import (
    get_all_medias_transition,
    write_media_table_transition,
)
from ofscraper.db.operations_.others import (
    get_all_others_transition,
    get_all_products_transition,
    write_others_table_transition,
    write_products_table_transition,
)
from ofscraper.db.operations_.posts import (
    get_all_posts_transition,
    write_post_table_transition,
)
from ofscraper.db.operations_.profile import (
    get_all_models,
    get_all_profiles,
    write_models_table,
    write_profile_table_transition,
)
from ofscraper.db.operations_.stories import (
    get_all_stories_transition,
    write_stories_table_transition,
)
from ofscraper.db.operations_.messages import (
    get_all_messages_transition,
    write_messages_table_transition,
)
from ofscraper.utils.context.run_async import run


log = logging.getLogger("shared")


@run
async def batch_database_changes(new_root, old_root):
    
    if not pathlib.Path(old_root).is_dir():
        raise FileNotFoundError("Path is not dir")
    old_root=pathlib.Path(old_root) 
    new_root=pathlib.Path(new_root)
    new_root.mkdir(exist_ok=True,parents=True)
    new_db_path=new_root/"user_data.db"
    db_merger=MergeDatabase(new_db_path)
    
    await create_tables(db_path=new_db_path)
    for ele in paths.get_all_db(old_root):
        if ele == new_db_path:
            continue
        log.info(f"Merging {ele} with {new_db_path}")
        try:
            model_id = get_single_model_via_profile(db_path=ele)
            if not model_id:
                raise Exception("No model ID")
            elif not str(model_id).isnumeric():
                raise Exception("Model ID is not numeric")
            await create_tables(db_path=ele)
            await modify_tables(model_id=model_id, db_path=ele)
            await db_merger(ele)

        except Exception as E:
            log.error(f"Issue getting required info for {ele}")
            log.traceback_(E)
            log.traceback_(traceback.format_exc())

class MergeDatabase():
    def __init__(self,new_db_path):
         self._data_init=False
         self._new_db=new_db_path
         self._media_keys=["media_id", "model_id"]
         self._label_keys=["post_id", "label_id", "model_id"]
         self._common_key=["post_id", "model_id"]
         self._profile_key=["user_id","username"]
         self._model_key="model_id"

    async def __call__(self, old_db_path):
        """
        This method is called when the object is used like a function.
        """
        await self._data_initializer()
        return await self.merge_database(old_db_path)
    async def _data_initializer(self):
        if not self._data_init:
            self._curr_labels =set(list(map(lambda x:tuple(x[key] for key in self._label_keys ),await get_all_labels_transition(db_path=self._new_db))))
            self._curr_medias= set(list(map(lambda x:tuple(x[key] for key in self._media_keys ),await get_all_medias_transition(db_path=self._new_db))))
            self._curr_posts =set(list(map(lambda x:tuple(x[key] for key in self._common_key ),await get_all_posts_transition(db_path=self._new_db))))
            self._curr_products =set(list(map(lambda x:tuple(x[key] for key in self._common_key ),await get_all_products_transition(db_path=self._new_db))))
            self._curr_others =set(list(map(lambda x:tuple(x[key] for key in self._common_key ),await get_all_others_transition(db_path=self._new_db))))
            self._curr_stories =set(list(map(lambda x:tuple(x[key] for key in self._common_key ),await get_all_stories_transition(db_path=self._new_db))))
            self._curr_messages =set(list(map(lambda x:tuple(x[key] for key in self._common_key ),await get_all_messages_transition(db_path=self._new_db))))
            self._curr_profiles =set(list(map(lambda x:tuple(x[key] for key in self._profile_key),await get_all_profiles(db_path=self._new_db))))
            self._curr_models =set(list(map(lambda x:x[self._model_key],await get_all_models(db_path=self._new_db))))
        self._data_init=True

    async def merge_database(self, db_path):
            await self.merge_media_helper(db_path)
            await self.merge_label_helper( db_path)
            await self.merge_posts_helper( db_path)
            await self.merge_products_helper(db_path)
            await self.merge_others_helper(db_path)
            await self.merge_stories_helper(db_path)
            await self.merge_profiles_helper(db_path)
            await self.merge_models_helper(db_path)
            await self.merge_messages_helper(db_path)



       
        

    async def merge_media_helper(self,old_db):
        keys = self._media_keys
        inserts_old_db = await get_all_medias_transition(db_path=old_db)
        await write_media_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_medias, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_medias.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_label_helper(self,old_db):
        keys = self._label_keys
        inserts_old_db = await get_all_labels_transition(db_path=old_db)
        await write_labels_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_labels, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_labels.update( map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_posts_helper(self,old_db):
        keys = self._common_key

        inserts_old_db = await get_all_posts_transition(db_path=old_db)
        await write_post_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_posts, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_posts.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))
        


    async def merge_products_helper(self,old_db):
        keys = self._common_key
        inserts_old_db = await get_all_products_transition(db_path=old_db)
        await write_products_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_products, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_products.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_others_helper(self,old_db):
        keys = self._common_key


        inserts_old_db = await get_all_others_transition(db_path=old_db)
        await write_others_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in  self._curr_others, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_others.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_stories_helper(self,old_db):
        global curr_stories
        keys = self._common_key
        inserts_old_db = await get_all_stories_transition(db_path=old_db)
        await write_stories_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_stories, inserts_old_db
                )
            ),
            db_path=self._new_db,

        )

        self._curr_stories.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_profiles_helper(self,old_db):
        keys = self._profile_key
        inserts_old_db = await get_all_profiles(db_path=old_db)
        await write_profile_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_profiles, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_profiles.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))


    async def merge_models_helper(self,old_db):
        inserts_old_db = get_single_model_via_profile(db_path=old_db)
        (
            await write_models_table(
                model_id=inserts_old_db,
                db_path=self._new_db,
            )
            if inserts_old_db not in self._curr_models
            else None
        )
        self._curr_models.add(inserts_old_db)


    async def merge_messages_helper(self,old_db):
        keys = self._common_key
        inserts_old_db = await get_all_messages_transition(db_path=old_db)
        await write_messages_table_transition(
            list(
                filter(
                    lambda x: tuple(x[key] for key in keys) not in self._curr_messages, inserts_old_db
                )
            ),
            db_path=self._new_db,
        )
        self._curr_messages.update(map(
                    lambda x: tuple(x[key] for key in keys), inserts_old_db
                ))
