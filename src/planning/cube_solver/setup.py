from setuptools import find_packages, setup

package_name = 'cube_solver'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'rubik-solver-py==0.1.1'],
    zip_safe=True,
    maintainer='jeonjihwan',
    maintainer_email='jeonjihwan@todo.todo',
    description='Kociemba cube-solving ROS 2 service',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'cube_solver = cube_solver.solver_node:main',
        ],
    },
)
