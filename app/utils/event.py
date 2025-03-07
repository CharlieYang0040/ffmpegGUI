# # app/utils/event.py
# class Event:
#     def __init__(self):
#         self.handlers = []
    
#     def add_handler(self, handler):
#         self.handlers.append(handler)
#         return handler
    
#     def remove_handler(self, handler):
#         self.handlers.remove(handler)
    
#     def fire(self, *args, **kwargs):
#         for handler in self.handlers:
#             handler(*args, **kwargs)