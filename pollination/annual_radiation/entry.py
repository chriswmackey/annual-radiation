from pollination_dsl.dag import Inputs, DAG, task, Outputs
from dataclasses import dataclass
from pollination.honeybee_radiance.sun import CreateSunMatrix, ParseSunUpHours
from pollination.honeybee_radiance.translate import CreateRadianceFolder
from pollination.honeybee_radiance.octree import CreateOctree, CreateOctreeWithSky
from pollination.honeybee_radiance.sky import CreateSkyDome, CreateSkyMatrix


# input/output alias
from pollination.alias.inputs.model import hbjson_model_input
from pollination.alias.inputs.wea import wea_input
from pollination.alias.inputs.north import north_input
from pollination.alias.outputs.daylight import sort_annual_daylight_results

from ._raytracing import AnnualRadiationRayTracing


@dataclass
class AnnualRadiationEntryPoint(DAG):
    """Annual radiation entry point."""

    # inputs
    north = Inputs.float(
        default=0,
        description='A number for rotation from north.',
        spec={'type': 'number', 'minimum': 0, 'maximum': 360},
        alias=north_input
    )

    sensor_count = Inputs.int(
        default=200,
        description='The maximum number of grid points per parallel execution.',
        spec={'type': 'integer', 'minimum': 1}
    )

    radiance_parameters = Inputs.str(
        description='Radiance parameters for ray tracing.',
        default='-ab 2 -ad 5000 -lw 2e-05'
    )

    model = Inputs.file(
        description='A Honeybee model in HBJSON file format.',
        extensions=['json', 'hbjson'],
        alias=hbjson_model_input
    )

    wea = Inputs.file(
        description='Wea file.',
        extensions=['wea'],
        alias=wea_input
    )

    @task(template=CreateSunMatrix)
    def generate_sunpath(self, north=north, wea=wea, output_type=1):
        """Create sunpath for sun-up-hours."""
        return [
            {'from': CreateSunMatrix()._outputs.sunpath, 'to': 'resources/sunpath.mtx'},
            {
                'from': CreateSunMatrix()._outputs.sun_modifiers,
                'to': 'resources/suns.mod'
            }
        ]

    @task(template=CreateRadianceFolder)
    def create_rad_folder(self, input_model=model):
        """Translate the input model to a radiance folder."""
        return [
            {'from': CreateRadianceFolder()._outputs.model_folder, 'to': 'model'},
            {
                'from': CreateRadianceFolder()._outputs.sensor_grids_file,
                'to': 'results/direct/grids_info.json'
            },
            {
                'from': CreateRadianceFolder()._outputs.sensor_grids_file,
                'to': 'results/total/grids_info.json'
            },
            {
                'from': CreateRadianceFolder()._outputs.sensor_grids,
                'description': 'Sensor grids information.'
            }
        ]

    @task(template=CreateOctree, needs=[create_rad_folder])
    def create_octree(self, model=create_rad_folder._outputs.model_folder):
        """Create octree from radiance folder."""
        return [
            {
                'from': CreateOctreeWithSky()._outputs.scene_file,
                'to': 'resources/scene.oct'
            }
        ]

    @task(
        template=CreateOctreeWithSky, needs=[generate_sunpath, create_rad_folder]
    )
    def create_octree_with_suns(
        self, model=create_rad_folder._outputs.model_folder,
        sky=generate_sunpath._outputs.sunpath
    ):
        """Create octree from radiance folder and sunpath for direct studies."""
        return [
            {
                'from': CreateOctreeWithSky()._outputs.scene_file,
                'to': 'resources/scene_with_suns.oct'
            }
        ]

    @task(template=CreateSkyDome)
    def create_sky_dome(self):
        """Create sky dome for daylight coefficient studies."""
        return [
            {'from': CreateSkyDome()._outputs.sky_dome, 'to': 'resources/sky.dome'}
        ]

    @task(template=CreateSkyMatrix)
    def create_indirect_sky(
        self, north=north, wea=wea, sky_component='-s', output_type=1
    ):
        return [
            {
                'from': CreateSkyMatrix()._outputs.sky_matrix,
                'to': 'resources/sky_direct.mtx'
            }
        ]

    @task(template=ParseSunUpHours, needs=[generate_sunpath])
    def parse_sun_up_hours(self, sun_modifiers=generate_sunpath._outputs.sun_modifiers):
        return [
            {
                'from': ParseSunUpHours()._outputs.sun_up_hours,
                'to': 'results/total/sun-up-hours.txt'
            },
            {
                'from': ParseSunUpHours()._outputs.sun_up_hours,
                'to': 'results/direct/sun-up-hours.txt'
            }
        ]

    @task(
        template=AnnualRadiationRayTracing,
        needs=[
            create_sky_dome, create_octree_with_suns, create_octree, generate_sunpath,
            create_indirect_sky, create_rad_folder
        ],
        loop=create_rad_folder._outputs.sensor_grids,
        sub_folder='initial_results/{{item.name}}',  # create a subfolder for each grid
        sub_paths={'sensor_grid': 'grid/{{item.name}}.pts'}  # sub_path for sensor_grid arg
    )
    def annual_radiation_raytracing(
        self,
        sensor_count=sensor_count,
        radiance_parameters=radiance_parameters,
        octree_file_with_suns=create_octree_with_suns._outputs.scene_file,
        octree_file=create_octree._outputs.scene_file,
        grid_name='{{item.name}}',
        sensor_grid=create_rad_folder._outputs.model_folder,
        sky_dome=create_sky_dome._outputs.sky_dome,
        sky_matrix_indirect=create_indirect_sky._outputs.sky_matrix,
        sunpath=generate_sunpath._outputs.sunpath,
        sun_modifiers=generate_sunpath._outputs.sun_modifiers
    ):
        pass

    total_radiation = Outputs.folder(
        source='results/total',
        alias=sort_annual_daylight_results
    )

    direct_radiation = Outputs.folder(
        source='results/direct',
        alias=sort_annual_daylight_results
    )