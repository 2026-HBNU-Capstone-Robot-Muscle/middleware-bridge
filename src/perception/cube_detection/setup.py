from setuptools import find_packages, setup

package_name = 'cube_detection'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/model', ['model/cube-detector.pt']),
    ],
    install_requires=['setuptools', 'ultralytics>=8.0,<9'],
    zip_safe=True,
    maintainer='jeonjihwan',
    maintainer_email='jeonjihwan@todo.todo',
    description='YOLO OBB cube-face perception node',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'cube_detector = cube_detection.detector_node:main',
            'cube_state_assembler = cube_detection.state_assembler_node:main',
            'cube_offline_replay = cube_detection.offline_replay_node:main',
        ],
    },
)
