from ofscraper.classes.table.fields.numfield import PostiveNumField
import ofscraper.utils.args.mutators.write as write_args
import ofscraper.utils.args.accessors.read as read_args


class SizeMaxField(PostiveNumField):
    def compose(self):
        yield self.Field(
            placeholder=self.filter_name.capitalize().replace("_", " "),
            id=f"{self.filter_name}_input",
            value=self.default,
        )
    def on_input_changed(self,event):
        value=event.value if event.value else "0"
        args=read_args.retriveArgs()
        args.size_max=int(value)
        write_args.setArgs(args)


class SizeMinField(PostiveNumField):
    def compose(self):
        yield self.Field(
            placeholder=self.filter_name.capitalize().replace("_", " "),
            id=f"{self.filter_name}_input",
            value=self.default,
        )      

    def on_input_changed(self,event):
        value=event.value if event.value else "0"
        args=read_args.retriveArgs()
        args.size_min=int(value)
        write_args.setArgs(args)
